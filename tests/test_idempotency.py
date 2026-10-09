from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from app import jobs, main


@pytest.fixture
def isolated_store(monkeypatch):
    root = Path("data/test-tmp")
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as directory:
        monkeypatch.setattr(jobs, "DATABASE_PATH", Path(directory) / "jobs.sqlite3")
        monkeypatch.setattr(jobs, "JOB_UPLOADS", Path(directory) / "uploads")
        monkeypatch.setattr(main, "JOB_BACKEND", "celery")
        monkeypatch.setattr(main, "publish_job", lambda job_id: None)
        yield jobs.JobStore()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_same_key_reuses_job_and_conflict_returns_409(isolated_store, anyio_backend):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        first = await client.post("/api/jobs/", headers={"Idempotency-Key": "retry-1"}, files={"file": ("a.kml", b"first")})
        repeated = await client.post("/api/jobs/", headers={"Idempotency-Key": "retry-1"}, files={"file": ("renamed.kml", b"first")})
        conflict = await client.post("/api/jobs/", headers={"Idempotency-Key": "retry-1"}, files={"file": ("a.kml", b"different")})
        assert first.status_code == repeated.status_code == 202
        assert first.json()["job_id"] == repeated.json()["job_id"]
        assert conflict.status_code == 409
        assert len(list(jobs.JOB_UPLOADS.iterdir())) == 1


def test_concurrent_key_and_atomic_publication_record(isolated_store):
    isolated_store.initialize()
    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(lambda _: isolated_store.create("file.kml", b"payload", "concurrent"), range(8)))
    assert len({job.job_id for job in created}) == 1
    with isolated_store._connect() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM job_publications WHERE status='PENDING'").fetchone()[0] == 1
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_publication_leases"


def test_legacy_jobs_survive_migration(isolated_store):
    with isolated_store._connect() as db:
        db.execute("""CREATE TABLE jobs (id TEXT PRIMARY KEY, filename TEXT NOT NULL,
        upload_path TEXT NOT NULL, status TEXT NOT NULL, source_crs TEXT,
        feature_count INTEGER DEFAULT 0, processed_count INTEGER DEFAULT 0,
        successful_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0,
        error_message TEXT, created_at TEXT NOT NULL, started_at TEXT,
        completed_at TEXT, results_json TEXT)""")
        db.execute("INSERT INTO jobs (id,filename,upload_path,status,created_at) VALUES ('legacy','old.kml','old','COMPLETED','2026-01-01')")
    isolated_store.initialize()
    assert isolated_store.get("legacy").filename == "old.kml"
