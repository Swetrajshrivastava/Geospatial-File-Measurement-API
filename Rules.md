# Engineering Rules for AI Contributors

## Scope and safety

- Read the relevant code and documents before changing behavior.
- Keep changes focused on the requested task; do not rewrite unrelated modules.
- Do not add credentials, API tokens, or uploaded source data to the repository.
- Do not weaken file-size, archive-path, or CRS safeguards merely to make an upload pass.
- Preserve user-authored changes and existing public API routes unless a deliberate breaking change is requested.

## Python and API conventions

- Target Python 3.11–3.13. Keep type hints on public functions and Pydantic models for API payloads.
- Keep routes thin. Place parsing and geospatial rules in the processing layer, and persistence behind the repository interface.
- Return deliberate HTTP errors with safe, useful messages. Never expose a raw exception or file-system path to clients.
- Maintain trailing slashes on existing endpoints and update the README/OpenAPI examples when contracts change.
- Use `pathlib`, context managers, and small testable functions.

## Geospatial correctness

- Never use `.area` or `.length` on longitude/latitude geometry without transforming it first.
- Keep output geometry in its source CRS; transform only a temporary geometry used for measurement.
- Keep measurement units explicit: `m` for length and `m²` for area.
- If CRS is absent, invalid, or a geometry cannot be transformed, return `UNAVAILABLE`; do not guess silently.
- Unsupported geometries must be returned with their metadata and a graceful status.
- When adding a format, document its default CRS and add representative fixtures/tests.

## Quality gates

- Add or update tests for every behavior change, including one success and relevant failure/edge case.
- Run `pytest` in a supported environment before handoff.
- Run `python -m compileall -q app tests` as a quick syntax check.
- Update `README.md`, `PRD.md`, `Architecture.md`, and `Task.md` if the change materially alters product behavior or delivery status.
- Keep dependency additions minimal and pin them to compatible major-version ranges in `requirements.txt`.
