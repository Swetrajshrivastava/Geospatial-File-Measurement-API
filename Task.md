# Delivery Task List

## Completed

- [x] FastAPI application and health endpoint.
- [x] KML upload and parsing.
- [x] ZIP Shapefile upload, validation, and Fiona parsing.
- [x] Feature metadata and GeoJSON geometry response.
- [x] CRS-aware polygon area and line length calculation.
- [x] Graceful handling for points, unsupported geometry, invalid geometry, and missing CRS.
- [x] API tests and core README documentation.
- [x] Project guidance documents.
- [x] Hardened KML parsing, ZIP-directory handling, and multi-zone measurement behavior; added error-path/unit tests.
- [x] Validated runtime under Python 3.13; full suite passes with KML, real zipped Shapefile, safety, unit, 404, incomplete archive, and multi-zone coverage.
- [x] Started Uvicorn and verified `/health/` and OpenAPI over HTTP; removed generated processing artifacts after validating workspace cleanup.
- [x] Phase 1 measurement transparency: added source/measurement CRS metadata, explicit geometry validation statuses, and QA coverage for validation, multipart totals, limits, and cleanup.
- [x] Phase 2 exports: CSV and GeoJSON downloads with CRS/measurement metadata and regression coverage.
- [x] Phase 3 prototype: SQLite-backed job history with FastAPI background processing, status/progress, persisted results, and job exports.

## Next priority

- [x] Phase 4 Stage 2: publication reconciliation, atomic publisher claims, lease recovery, bounded backoff, and failure-injection tests. Suite: 34 passed.
- [ ] Phase 4 Stage 3: worker leases, heartbeat renewal, and fencing of writes/cleanup.

- [x] Phase 4 stage 1: non-destructive Alembic migration, idempotent upload header, atomic publication intent, and concurrent-submission tests. Suite: 29 passed.
- [ ] Phase 4 stages 2+: reconciliation dispatcher, leases/fencing, heartbeat renewal, bounded retries, and safe cleanup recovery.

- [x] Preserve 22-test baseline; add Compose, shared storage configuration, Celery registration, conditional claiming, and connection cleanup. Current suite: 24 passed.
- [ ] Validate Compose with live Redis and worker (Docker is unavailable on this machine).
- [x] Activate configurable Celery/local dispatch and test publication failure handling. Full suite: 26 passed.
- [ ] Implement bounded worker retries, stale-job recovery, publication reconciliation, and abandoned-upload retention cleanup.

> Note: the Python environment and automated test run are complete; the first two legacy checklist entries below are retained only as historical context.

- [ ] Use Python 3.11–3.13, create a virtual environment, install `requirements.txt`, and run `pytest`.
- [ ] Manually upload a real KML and a zipped Shapefile through `/docs`.
- [ ] Create the public GitHub repository, push the project, and add its URL to the submission.
- [ ] Add CI with GitHub Actions using Python 3.13.

## Recommended improvements

- [ ] Add real Shapefile fixture tests (including EPSG:4326 and missing `.prj`).
- [ ] Add tests for archive traversal, multiple `.shp` files, malformed KML, and unsupported geometry collections.
- [ ] Replace in-memory records with PostgreSQL/PostGIS and persist source files to object storage.
- [ ] Move processing to a background worker and expose `PENDING`, `PROCESSING`, `COMPLETED`, and `FAILED` statuses.
- [ ] Replace process-local background tasks with a durable queue and recovery policy if deploying beyond the local prototype.
- [ ] Add authentication, rate limits, audit logging, malware scanning, monitoring, and retention cleanup.
- [ ] Add GeoJSON/GeoPackage support after specifying CRS and layer-selection behavior.
- [ ] Decide and document a geodesic or approved regional CRS policy for large/cross-zone datasets.
- [ ] Build the optional accessible map/table UI described in `design.md`.
