# Design Direction

## Current product surface

This project is API-first. The primary interface is Swagger UI at `/docs`, generated from FastAPI's OpenAPI schema. There is no custom browser UI yet.

## API experience

- Use plain, consistent resource paths: `/api/files/`, `/api/files/{id}/`, and `/api/files/{id}/measurements/`.
- Use predictable JSON keys and uppercase lifecycle/result statuses such as `COMPLETED`, `NOT_APPLICABLE`, and `UNAVAILABLE`.
- Keep a file summary compact; place full geometry and attributes in the measurements resource.
- Make errors actionable: state the allowed file types, file-size limit, archive problem, or missing record without exposing internals.
- Use GeoJSON-style geometry objects so maps and GIS clients can consume them directly.

## Future web UI

If a UI is added, build a responsive, accessible workflow with three states:

1. **Upload** — a clear drag-and-drop zone plus file picker. State supported formats (`.kml`, zipped Shapefile), 50 MB limit, and privacy/retention policy.
2. **Summary** — display filename, feature count, CRS, status, and concise warning cards for unavailable measurements.
3. **Explore** — a map beside a filterable feature table. Selecting a row highlights the geometry; measurements show values and units prominently.

Use a calm, data-focused palette: deep slate text, off-white background, one blue/teal action color, and amber only for warnings. Never use color as the sole way to convey status. Ensure keyboard navigation, visible focus, semantic labels, and readable contrast.

## Data presentation rules

- Show length in `m` and area in `m²`, with rounded display values but retain API precision.
- Always show CRS beside a measurement or make it easily discoverable.
- State that local UTM projection is used for measurements; avoid implying survey-grade accuracy.
- Show points as “No measurement required,” not as an error.
