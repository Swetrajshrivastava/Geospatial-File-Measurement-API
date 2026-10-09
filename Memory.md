# Project Memory

## Identity

- Project: **Geospatial File Measurement API**.
- Framework: FastAPI.
- Current implementation is API-only, with no custom UI.
- Supported input: `.kml` and `.zip` containing exactly one Shapefile.
- Python target: 3.11–3.13. The local interpreter used during initial setup was Python 3.14, where Fiona installation failed because a compatible GDAL wheel was unavailable.

## AI context-document workflow

- This project uses the six-document workflow from [vibe-coding-context-kit](https://github.com/RahulMirji/vibe-coding-context-kit/tree/main/ai-context-docs).
- Treat `PRD.md`, `Architecture.md`, `Rules.md`, and `design.md` as stable documents: update them only when the product, architecture, coding policy, or design system changes.
- Treat `Task.md` and this file as living documents: read both at the start of each work session, update `Task.md` when work changes state, and record lasting decisions, constraints, failures, and lessons here.
- Before building a feature, read the PRD, architecture, rules, the current task, and memory. Read `design.md` for UI work.

## Stable API contract

- `GET /health/` returns `{"status": "ok"}`.
- `POST /api/files/` accepts multipart field `file` and returns `201` plus `id`, `filename`, `feature_count`, `crs`, and `status`.
- `GET /api/files/{id}/` returns the same file summary.
- `GET /api/files/{id}/measurements/` returns file summary and a `features` list.
- `GET /api/files/{id}/measurements/export/?format=csv` downloads a row per feature; `format=geojson` downloads a FeatureCollection with source geometry and measurement metadata.
- `POST /api/jobs/` creates a SQLite-persisted job and returns `202`; status, results, and exports are available under `/api/jobs/{id}/...`.
- Each feature exposes `feature_id`, `geometry_type`, `geometry`, `crs`, `properties`, `measurement`, `measurement_status`, and optional `message`.

## Important implementation decisions

- KML is parsed directly with Python XML parsing rather than relying on an optional GDAL KML driver.
- Shapefiles are read with Fiona. Shapely handles geometry and PyProj performs transformations.
- Geographic inputs are measured after a temporary transformation to the feature's local UTM zone; output geometry remains in its original CRS.
- Polygon/MultiPolygon area uses `m²`; LineString/MultiLineString length uses `m`.
- Point geometries intentionally receive `NOT_APPLICABLE`.
- `crs` is retained as the backward-compatible source CRS; `source_crs` states this role explicitly. `measurement_crs` is populated only after a successful calculation and is otherwise `null`.
- Feature validation statuses are deliberate: `MISSING`, `EMPTY`, `INVALID`, `NOT_APPLICABLE`, `UNAVAILABLE`, and `COMPLETED`. A `COMPLETED` measurement includes type, value, unit, and status metadata.
- Exports preserve geometry in its source CRS. GeoJSON responses include `metadata.geometry_crs` because consumers often assume WGS 84; do not imply a projection conversion occurred during export.
- Geometry errors and absent CRS use per-feature `UNAVAILABLE` instead of failing a valid whole upload.
- Upload and extraction workspaces are deleted after processing; metadata is held only in a thread-safe in-memory repository and is non-durable by design.
- Upload limit is 50 MB. ZIP extraction blocks path traversal, excess members, and excessive uncompressed content.
- KML parsing uses `defusedxml` to reject unsafe XML entity constructs.
- A feature crossing the antimeridian or UTM-zone boundary is deliberately returned as `UNAVAILABLE`; do not silently choose one zone. A geodesic policy is future work.
- Runtime validation passed on Python 3.13.15 using the project `.venv`; this was required because Python 3.14 did not have a usable Fiona/GDAL wheel. Tests use `httpx.AsyncClient` with ASGI transport rather than deprecated `TestClient`, and generate a real EPSG:4326 zipped Shapefile to test the Fiona path.
- Final local validation result: `9 passed in 0.67s` via `.venv\Scripts\python.exe -m pytest -v -p no:cacheprovider`. Uvicorn also returned `200` from `/health/` and `/openapi.json`. The cache plugin was disabled only for validation because this environment has a locked generated `.pytest_cache` directory; it is not an application defect.
- Jobs use `data/geospatial_jobs.sqlite3` with WAL/busy-timeout settings and persist serialized feature records. FastAPI `BackgroundTasks` is intentionally process-local: no retries or crash recovery are claimed; a real queue is a future deployment concern.
- Job `failed_count` represents job/worker failures, not feature data outcomes such as `UNAVAILABLE` or `INVALID`; those remain visible per feature while a successfully processed job is `COMPLETED`.

## Change discipline

Phase 4 Stage 2: `0002_publication_leases` adds publisher tokens/expiry. API and reconciler share claims; publication failures retry after exponential backoff (cap 300 seconds, eight attempts). Run `python -m app.reconciliation` for periodic dispatch; Compose includes it. Reconciliation does not reset PROCESSING jobs or perform geometry/cleanup. 34 tests pass; worker leases/fencing and live broker verification remain pending.

Phase 4 stage 1: Alembic revision `0001_reliability` adopts legacy jobs and adds reliability schema. Idempotency keys are globally unique for this single-user prototype; fingerprints include bytes and parser format. Concurrent submissions serialize with BEGIN IMMEDIATE. Jobs/publication intent commit atomically. Matching failed-job retries reuse the existing ID/status; automatic recovery is not implemented yet. 29 tests pass. Lease fields are preparatory, not active fencing.

Worker dependencies live in `requirements-worker.txt`; `JOB_BACKEND=celery` activates task publication and `local` remains the development default. Compose chooses Celery and shares `/data` with one solo worker. Local suite: 26 passed; no real Redis delivery verification because Docker is unavailable. Failed publication returns 503 with the job ID, conditionally marks queued jobs failed, and retains input for diagnosis. Atomic claims and SQLite connection cleanup are implemented; worker retries, crash recovery, publication reconciliation and abandoned-upload cleanup remain pending.

- Preserve the trailing-slash routes and response keys unless versioning a breaking change.
- Add tests with any parsing, measurement, validation, status, or API contract change.
- Keep this file current when a decision, constraint, or important failure mode changes.
- Read `Rules.md` before implementing changes and consult `Task.md` for priority work.
