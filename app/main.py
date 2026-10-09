from __future__ import annotations

from pathlib import Path
import os
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.exporter import build_csv_report, build_geojson_report
from app.jobs import IdempotencyConflict, job_store, process_job
from app.models import FileSummary, JobSummary, MeasurementsResponse
from app.processor import MAX_UPLOAD_BYTES, ProcessingError, process_upload
from app.repository import repository

STORAGE_ROOT = Path("data/uploads")
JOB_BACKEND = os.getenv("JOB_BACKEND", "local").lower()
if JOB_BACKEND not in {"local", "celery"}:
    raise ValueError("JOB_BACKEND must be local or celery")


def publish_job(job_id: str) -> None:
    from app.tasks import process_job_task

    process_job_task.apply_async(args=[job_id], retry=False)

app = FastAPI(title="Geospatial File Measurement API", version="1.0.0", description="Upload KML or zipped Shapefiles and obtain CRS-aware measurements.")


@app.get("/health/")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/files/", response_model=FileSummary, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...)) -> FileSummary:
    filename = file.filename or ""
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded file exceeds the 50 MB limit.")
    try:
        processed = process_upload(filename, contents, STORAGE_ROOT)
    except ProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=422, detail="The file could not be read as geospatial data.")
    repository.save(processed)
    return processed.summary


@app.post("/api/jobs/", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED)
async def create_job(background_tasks: BackgroundTasks, file: UploadFile = File(...), idempotency_key: str | None = Header(None, alias="Idempotency-Key", min_length=1, max_length=200)) -> JobSummary:
    filename = file.filename or ""
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded file exceeds the 50 MB limit.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".kml", ".zip"}:
        raise HTTPException(status_code=422, detail="Only .kml files and .zip Shapefile archives are accepted.")
    if not contents:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    try:
        job = await run_in_threadpool(job_store.create, filename, contents, idempotency_key)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job.status != "QUEUED":
        return job
    if JOB_BACKEND == "local":
        background_tasks.add_task(process_job, job.job_id)
        job_store.mark_published(job.job_id)
    else:
        try:
            from app.reconciliation import deliver

            await run_in_threadpool(deliver, job.job_id, publish_job)
        except Exception:
            # Retain the upload for diagnosis; an ambiguous publication could have
            # reached Redis, so never delete a file another worker might be reading.
            raise HTTPException(status_code=503, detail={"message": "Job could not be queued.", "job_id": job.job_id})
    return job


@app.get("/api/jobs/{job_id}/", response_model=JobSummary)
def get_job(job_id: str) -> JobSummary:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    return job


def _job_results(job_id: str) -> MeasurementsResponse:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    results = job_store.results(job_id)
    if results is None:
        raise HTTPException(status_code=409, detail=f"Measurements are unavailable while job status is {job.status}.")
    return results


@app.get("/api/jobs/{job_id}/measurements/", response_model=MeasurementsResponse)
def get_job_measurements(job_id: str) -> MeasurementsResponse:
    return _job_results(job_id)


@app.get("/api/jobs/{job_id}/measurements/export/")
def export_job_measurements(job_id: str, export_format: Literal["csv", "geojson"] = Query(..., alias="format")) -> Response:
    results = _job_results(job_id)
    from app.repository import ProcessedFile

    item = ProcessedFile(summary=results.file, features=results.features)
    filename = f"job-measurements-{job_id}"
    if export_format == "csv":
        return Response(content=build_csv_report(item), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
    return JSONResponse(content=build_geojson_report(item), media_type="application/geo+json", headers={"Content-Disposition": f'attachment; filename="{filename}.geojson"'})


@app.get("/api/files/{file_id}/", response_model=FileSummary)
def get_file(file_id: str) -> FileSummary:
    item = repository.get(file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    return item.summary


@app.get("/api/files/{file_id}/measurements/", response_model=MeasurementsResponse)
def get_measurements(file_id: str) -> MeasurementsResponse:
    item = repository.get(file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    return MeasurementsResponse(file=item.summary, features=item.features)


@app.get("/api/files/{file_id}/measurements/export/")
def export_measurements(file_id: str, export_format: Literal["csv", "geojson"] = Query(..., alias="format")) -> Response:
    item = repository.get(file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    filename = f"measurements-{item.summary.id}"
    if export_format == "csv":
        return Response(
            content=build_csv_report(item),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    return JSONResponse(
        content=build_geojson_report(item),
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}.geojson"'},
    )
