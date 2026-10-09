# Geospatial File Measurement API

A FastAPI backend that accepts a KML file or a ZIP archive containing a Shapefile, extracts its features, and returns CRS-aware area and length measurements.

## Setup

Requires Python 3.11–3.13 and the native libraries required by Fiona/GDAL (the pre-built Python wheels work on most Windows, macOS, and Linux installations). Python 3.14 support depends on a future Fiona/GDAL wheel release.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for Swagger UI. Run the automated checks with:

```powershell
python -m pytest -v -p no:cacheprovider
```

If the Windows launcher cannot locate Python 3.13, use the full path to its `python.exe` for environment creation. Worker tests require `pip install -r requirements-worker.txt`; otherwise the optional Celery test module is skipped. Latest recorded full validation: 34 tests passed. The cache plugin is disabled here to avoid a local Windows cache-directory permission issue.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health/` | Liveness check |
| `POST` | `/api/files/` | Upload `.kml` or a `.zip` containing one `.shp` |
| `GET` | `/api/files/{id}/` | Uploaded-file metadata |
| `GET` | `/api/files/{id}/measurements/` | Extracted features and measurements |
| `GET` | `/api/files/{id}/measurements/export/?format=csv` | Download a CSV measurement report |
| `GET` | `/api/files/{id}/measurements/export/?format=geojson` | Download a GeoJSON measurement report |
| `POST` | `/api/jobs/` | Create a persistent background-processing job |
| `GET` | `/api/jobs/{id}/` | Retrieve persistent job status and progress |
| `GET` | `/api/jobs/{id}/measurements/` | Retrieve completed job measurements |
| `GET` | `/api/jobs/{id}/measurements/export/?format=...` | Export completed job results |

Upload a file:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/files/ -F "file=@survey.kml"
```

For the asynchronous prototype, submit to `/api/jobs/` instead. It returns `202 Accepted` with a job ID; poll `/api/jobs/{id}/` until the status is `COMPLETED`, `PARTIALLY_FAILED`, or `FAILED`.

Example response:

```json
{
  "id": "e5f4...",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

The measurements endpoint returns every feature's ID, geometry type and GeoJSON geometry, CRS, attributes, and measurement result. `crs` is retained for compatibility and equals the explicit `source_crs`; `measurement_crs` identifies the projected CRS actually used, or is `null` when no measurement was made. Successful measurement objects contain `type`, `value`, `unit`, and `status: COMPLETED`. Polygon and MultiPolygon areas use `m²`; LineString and MultiLineString lengths use `m`. Feature statuses distinguish `MISSING`, `EMPTY`, `INVALID`, `NOT_APPLICABLE`, `UNAVAILABLE`, and `COMPLETED` without failing the whole upload.

## Exports

Download a completed file's report with `format=csv` or `format=geojson`:

```powershell
curl.exe -OJ "http://127.0.0.1:8000/api/files/FILE_ID/measurements/export/?format=csv"
curl.exe -OJ "http://127.0.0.1:8000/api/files/FILE_ID/measurements/export/?format=geojson"
```

CSV has one row per feature with IDs, geometry type, source and measurement CRS, measurement type/value/unit, status, message, and JSON-encoded properties. The GeoJSON report preserves each source geometry and source properties, and adds measurement metadata under each feature's `properties`. Its top-level `metadata.geometry_crs` declares the preserved source CRS. This matters because GeoJSON consumers commonly assume WGS 84 longitude/latitude coordinates; KML exports use EPSG:4326, while a projected Shapefile export may not.

## Architecture and flow

`app/main.py` exposes HTTP endpoints. `app/processor.py` validates and parses files, turns each source feature into a stable response record, and calculates its measurement. `app/repository.py` is a small thread-safe in-memory adapter that stores completed records; replacing it with PostgreSQL/PostGIS or object storage does not affect the API layer.

The job API uses `app/jobs.py` for SQLite persistence, including feature results and publication intent. `app/tasks.py` runs the reusable processor through Celery; `app/reconciliation.py` republishes eligible outbox records with publisher leases and retry backoff. `app/exporter.py` generates reports from stored results, and Alembic manages schema changes. With `JOB_BACKEND=local`, FastAPI background tasks run jobs in the API process; with `celery`, Redis carries job IDs to a separate worker. Compose shares the SQLite database and upload directory between services.

1. The upload is size- and extension-validated (50 MB limit).
2. ZIP archives are guarded against path traversal, member-count, and decompression-size attacks, then read with Fiona. KML is parsed directly as KML 2.2.
3. Each geometry and property set is serialized into the measurements response.
4. The measurement engine transforms source geometry before measuring.
5. The temporary upload and extraction workspace is deleted after the metadata and measurements are captured.

## CRS handling

Measurements are never computed directly in degrees. Geographic data, including KML's required WGS 84 / EPSG:4326, is transformed to the UTM zone containing the geometry's representative point. Metre-based projected data is measured in its native CRS; other projected unit systems are also transformed to local UTM. This is an appropriate local-measurement default. For datasets spanning UTM zones or requiring legally defined survey accuracy, use a domain-selected CRS or geodesic calculation policy.

Features whose geographic bounds cross an UTM-zone boundary or the antimeridian are returned with an `UNAVAILABLE` measurement. This is intentional: a single local UTM projection would make a potentially misleading measurement. A future geodesic policy can support these cases explicitly.

## Design decisions

- **FastAPI:** concise type-safe endpoints and automatically generated OpenAPI documentation.
- **Fiona + Shapely + PyProj:** separates format reading, geometry operations, and coordinate transformations cleanly. KML parsing is native so deployments are not dependent on an optional GDAL KML driver.
- **Graceful feature errors:** missing, empty, invalid, unsupported, and unavailable measurements have explicit feature statuses so other features remain accessible.
- **Ephemeral metadata:** suitable for this assignment and simple local use. Production should add PostgreSQL/PostGIS, asynchronous workers for large uploads, authentication, malware scanning, quotas, observability, retention policies, and object storage.
- **SQLite + FastAPI BackgroundTasks:** job metadata and results persist locally in `data/geospatial_jobs.sqlite3`; uploads are held only while background processing runs. This demonstrates a simple async workflow without additional infrastructure. It is not a durable distributed queue: a process crash can leave a `PROCESSING` job unfinished, and multi-process deployments need a real task queue and shared storage.
- **Configurable Celery + Redis:** separate workers and publication reconciliation provide an alternative to local background tasks. SQLite with one worker keeps setup simple; PostgreSQL is the planned alternative for concurrent writers. Idempotent submissions and atomic claims tolerate duplicate requests/delivery. Worker crash recovery still requires leases and fencing.

## Learning and future scope

Learning demonstrated: multipart upload validation, safe archive/XML parsing, CRS transformations and explicit units, feature validation, multipart measurement tests, report serialization, SQLite transactions, schema migrations, idempotency keys, publication outbox recovery, and failure-injection testing. These concepts provide concrete backend and QA interview examples.

Future scope: worker leases and fencing, processing retries and recovery-safe cleanup, live Redis/Celery integration tests, GitHub Actions CI, PostgreSQL for concurrent workers, authentication and tenant-scoped idempotency, quotas/rate limits, pagination, geodesic or regional projection policies, additional vector formats, and an optional map preview. Database persistence, job status, exports, and real Shapefile regression tests are already implemented.

## Celery migration foundation

### Phase 4: migrations, idempotent uploads, and reconciliation

Run `python -m alembic upgrade head` before starting multiple API/worker processes. The initial migration adopts the existing jobs table without deleting stored results and adds publication, lease, and attempt metadata. Local first use also initializes the schema. Schema downgrade is intentionally blocked pending a data-retention plan.

An optional `Idempotency-Key` header on `POST /api/jobs/` reuses the original job when file bytes and parser format match; changed payloads return `409`. Renaming a file without changing its format or bytes does not create a new job. Keys are globally scoped in this single-user prototype; tenant-scoped keys are required if authentication is introduced. Matching retries return the original current job status, including `FAILED`; they do not automatically revive a failed job.

Jobs and publication intent are committed together. Failed/uncertain publication remains `PENDING` in `job_publications`. Run `python -m app.reconciliation --once` for one pass or `python -m app.reconciliation` for a five-second polling loop (Celery dependencies required). Compose includes this reconciler service. Run migrations before starting all services simultaneously on a new database.

API and reconciler share atomic publication claims with unique tokens and a 60-second lease. A crashed publisher's expired claim can be reclaimed. Delivery uses the job ID; a lost acknowledgement may cause duplicate delivery, which the current atomic worker claim rejects. Publication attempts are limited to eight, with exponential delays capped at 300 seconds. Exhausted records remain available for diagnosis; uploads are retained. Worker leases, heartbeat renewal, processing retries and recovery cleanup remain subsequent stages. The reconciler never processes geometry, resets PROCESSING jobs, or deletes input files. Live Redis-to-worker verification remains pending.

Install worker dependencies with `pip install -r requirements-worker.txt`. `app.tasks.process_job_task` registers `geospatial.process_job` and calls the existing processor using only the job ID. Set `JOB_BACKEND=celery` to publish API jobs through Redis; `JOB_BACKEND=local` (the development default) uses FastAPI background tasks. Compose sets the Celery backend automatically. Environment changes require restarting the API.

With Docker Desktop available, run `docker compose up --build -d` and `docker compose logs worker`. The API and worker share `/data` for SQLite and uploads; Redis uses append-only persistence. Settings are documented in `.env.example` and must match in both processes.

Local tests validate task registration, execution, duplicate delivery, persistence through a new store instance, cleanup, mocked API publication, and publication reconciliation. Broker publication failures return `503` with the persisted job ID and conditionally mark a still-queued job `FAILED`. Its upload is retained for reconciliation. The reconciler retries eligible publications within its attempt limit. Docker is unavailable in the current validation environment, so live Redis/worker delivery has not been verified. Bounded worker retries, stale-job recovery, and abandoned-upload retention cleanup remain release gates. A crashed worker can leave a job `PROCESSING`; do not manually reset it while another worker could still own it.

## GitHub submission commands

Public repository URL: pending. This workspace has no Git repository or configured remote; the example URL below is a placeholder, not a submitted repository.

Create a repository, then publish this folder:

```powershell
git init
git add .
git commit -m "Build geospatial measurement API"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/geospatial-file-measurement-api.git
git push -u origin main
```

Replace `YOUR-USERNAME` with your GitHub user name and share the resulting public repository URL.
