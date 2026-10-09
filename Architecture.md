# Architecture

## Overview

The application is a small layered FastAPI service. The HTTP layer contains no GIS calculation logic; the processor owns parsing, validation, CRS selection, and measurement.

```text
Client
  │ multipart upload / JSON requests
  ▼
FastAPI routes (app/main.py)
  │ validates HTTP contract
  ▼
Processing service (app/processor.py)
  ├─ validates upload and ZIP safety
  ├─ parses KML or Shapefile
  ├─ normalizes features to response models
  └─ transforms and measures geometry
  ▼
Repository adapter (app/repository.py)
  ▼
In-memory completed-file records
```

The job prototype adds a parallel workflow: `/api/jobs/` writes a SQLite job record and controlled local upload, then schedules `process_job` with FastAPI `BackgroundTasks`. The task calls the existing processor, persists serialized feature results and counters, marks a terminal status, and removes the raw upload.

## Modules

Publication reconciliation is implemented in `app/reconciliation.py`: API delivery and periodic scans share leased, token-conditional publication updates. Alembic revision `0002_publication_leases` adds publication claim fields. Retryable publication-failure jobs can return to QUEUED within the claim transaction; parser failures and PROCESSING jobs are excluded. At-least-once publication intentionally tolerates uncertain delivery. Worker ownership fencing remains a separate stage.

Alembic migrations adopt existing SQLite job history and add idempotency, publication, lease, and attempt schema. Submission uses a unique key index and `BEGIN IMMEDIATE` to serialize keyed creation. Fingerprints cover file bytes and parser format. Publication intent commits in the same transaction as the job. Lease/attempt columns currently prepare the next recovery stage and are not yet enforced by workers.

`app/celery_app.py` configures Redis and `app/tasks.py` registers a worker task calling the existing job service. `compose.yaml` shares SQLite/upload storage between API and a single worker. `JOB_BACKEND=celery` activates broker publication; the development default `local` uses BackgroundTasks. Publication runs off the event loop and returns `503` on failure, conditionally marking queued jobs failed while retaining input. Conditional job claiming prevents duplicate concurrent claims; SQLite connections close explicitly after each transaction. Stale-job recovery and publication reconciliation remain pending.

| Module | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app, routes, HTTP errors, upload-size read limit. |
| `app/processor.py` | File-format readers, archive protections, geometry normalization, CRS-aware calculations. |
| `app/exporter.py` | CSV and GeoJSON report serialization from completed feature records. |
| `app/jobs.py` | SQLite job store and in-process background job lifecycle. |
| `app/models.py` | Pydantic response contracts. |
| `app/repository.py` | Thread-safe in-memory persistence adapter. |
| `tests/test_api.py` | End-to-end API behavior for KML upload and errors. |

## Processing flow

1. The route reads at most 50 MB and sends bytes plus filename to `process_upload`.
2. KML is parsed as KML 2.2, whose coordinates are WGS 84 / EPSG:4326. Shapefile ZIPs are checked for unsafe paths, archive-member count, and decompressed size, then read through Fiona.
3. Every source item is converted to a GeoJSON-compatible geometry and JSON-safe properties, then classified as missing, empty, invalid, unsupported, unavailable, or measurable.
4. For valid polygons and lines, the processor selects a metre-based CRS and transforms the geometry with PyProj/Shapely before calculating. Responses retain the source CRS and expose the actual measurement CRS separately.
5. The resulting summary and feature records are stored and returned by ID; the upload/extraction workspace is removed after processing.

## CRS strategy

KML and other geographic CRS inputs are transformed to the UTM zone containing the feature's representative point. Existing projected CRS data in metre units is measured in place; projected data in another unit is transformed to local UTM. Missing CRS means no measurement is returned because a reliable result cannot be inferred.

UTM is a sensible local default, but it should be replaced with a domain-approved CRS or geodesic method for nationwide, cross-zone, legal, or high-precision calculations.

## Storage and scaling

The original file API uses the in-memory repository and therefore remains ephemeral. The new job API stores job metadata and results in SQLite, so completed jobs survive an application restart. It uses FastAPI background tasks, which are process-local and have no retry or crash recovery guarantee; this is a learning prototype, not a durable queue. Original job uploads are deleted after work completes. A production implementation should preserve the route contracts while using PostgreSQL/PostGIS, object storage with retention policy, and a dedicated worker queue.
