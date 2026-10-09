"""Worker entry points reuse the existing processing service."""
from app.celery_app import celery_app
from app.jobs import process_job


@celery_app.task(name="geospatial.process_job")
def process_job_task(job_id: str) -> None:
    process_job(job_id)
