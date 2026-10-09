from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

pytest.importorskip("celery")

from app import jobs
from app.tasks import process_job_task
from app.celery_app import celery_app


def test_registered_worker_executes_and_ignores_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path("data/test-tmp")
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as directory:
        monkeypatch.setattr(jobs, "DATABASE_PATH", Path(directory) / "jobs.sqlite3")
        monkeypatch.setattr(jobs, "JOB_UPLOADS", Path(directory) / "uploads")
        monkeypatch.setattr(jobs, "JOB_WORK", Path(directory) / "work")
        store = jobs.JobStore()
        job = store.create("point.kml", b'<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Point><coordinates>77,12</coordinates></Point></Placemark></kml>')
        assert celery_app.tasks["geospatial.process_job"].name == process_job_task.name
        process_job_task.apply(args=[job.job_id], throw=True)
        first = store.results(job.job_id)
        process_job_task.apply(args=[job.job_id], throw=True)
        assert store.results(job.job_id) == first
        assert jobs.JobStore().get(job.job_id).status == "COMPLETED"
        assert not list(jobs.JOB_UPLOADS.iterdir())


def test_claim_is_conditional(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path("data/test-tmp")
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as directory:
        monkeypatch.setattr(jobs, "DATABASE_PATH", Path(directory) / "jobs.sqlite3")
        monkeypatch.setattr(jobs, "JOB_UPLOADS", Path(directory) / "uploads")
        store = jobs.JobStore()
        job = store.create("test.kml", b"test")
        assert store.claim(job.job_id) is not None
        assert store.claim(job.job_id) is None
