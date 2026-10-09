# Product Requirements Document

## Product

Geospatial File Measurement API is a backend service that accepts a KML file or a ZIP archive containing one Shapefile and returns its extracted features plus reliable area and length measurements.

## Problem

Teams need a simple, programmatic way to inspect common vector geospatial files. Calculating directly from latitude/longitude coordinates produces values in degrees, not metres or square metres, so the service must handle coordinate reference systems (CRS) correctly.

## Users

- GIS analysts validating submitted survey data.
- Backend consumers that need feature metadata and basic measurements.
- Recruiters and reviewers assessing clean API and geospatial engineering practices.

## Goals

- Upload `.kml` and `.zip` Shapefile archives through HTTP.
- Extract ID, geometry type, GeoJSON geometry, CRS, and properties for every feature.
- Calculate polygon area and line length in metric units.
- Never calculate geographic-coordinate measurements in degrees.
- Return useful per-feature statuses for unsupported, invalid, or CRS-less data.
- Provide discoverable OpenAPI documentation and automated tests.

## Non-goals (current version)

- Rendering a map or providing a browser user interface.
- Editing geospatial features.
- Supporting raster files, GeoJSON, GeoPackage, or multiple Shapefile layers per upload.
- User accounts and multi-worker production deployment.
- Survey-grade / jurisdiction-specific measurement policies.

## Functional requirements

| Capability | Requirement |
| --- | --- |
| Upload | `POST /api/files/` accepts a KML or ZIP containing exactly one `.shp` file. |
| File summary | `GET /api/files/{id}/` returns ID, original filename, feature count, CRS, and processing status. |
| Feature results | `GET /api/files/{id}/measurements/` returns every parsed feature and its measurement result. |
| Polygon | Return area in square metres (`m²`). |
| LineString | Return length in metres (`m`). |
| Point / other | Return an explicit `NOT_APPLICABLE` or `UNAVAILABLE` status rather than failing the upload. |
| Safety | Limit uploads; reject unsafe archive paths and oversized archive contents. |
| Background jobs | Persist jobs/results in SQLite; select local execution or Celery via JOB_BACKEND; return explicit publication errors. |
| Submission retries | Optional Idempotency-Key reuses matching payload jobs and rejects conflicts with 409. |
| Publication recovery | Reconcile pending or expired publication claims with bounded backoff; retain input needed for delivery. |

## Success criteria

- A valid EPSG:4326 KML polygon produces a non-zero metric area.
- A valid EPSG:4326 KML line produces a non-zero metric length.
- A point is returned intact with no measurement required.
- A malformed file produces a client-safe `422` response.
- One bad feature does not discard valid features from the same source.

## Future scope

Persist records in PostgreSQL/PostGIS, store uploads in object storage, process large files in background workers, add authentication and quotas, support more vector formats, offer geodesic and user-selected CRS policies, and add a map-based UI.
