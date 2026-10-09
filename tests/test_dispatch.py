from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from app import jobs, main


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("broker_fails", [False, True])
async def test_celery_dispatch_and_publication_failure(monkeypatch: pytest.MonkeyPatch, anyio_backend: str, broker_fails: bool) -> None:
    root = Path("data/test-tmp")
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as directory:
        monkeypatch.setattr(jobs, "DATABASE_PATH", Path(directory) / "jobs.sqlite3")
        monkeypatch.setattr(jobs, "JOB_UPLOADS", Path(directory) / "uploads")
        monkeypatch.setattr(main, "JOB_BACKEND", "celery")
        published = []

        def publish(job_id: str) -> None:
            published.append(job_id)
            if broker_fails:
                raise ConnectionError("broker down")

        monkeypatch.setattr(main, "publish_job", publish)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.post("/api/jobs/", files={"file": ("sample.kml", b"test")})
            assert len(published) == 1
            job_id = published[0]
            persisted = jobs.job_store.get(job_id)
            assert response.status_code == (503 if broker_fails else 202)
            assert persisted.status == ("FAILED" if broker_fails else "QUEUED")
            assert list(jobs.JOB_UPLOADS.iterdir())  # Worker needs input; failed publication retains it.
            if broker_fails:
                assert response.json()["detail"]["job_id"] == job_id
                assert jobs.job_store.claim(job_id) is None
