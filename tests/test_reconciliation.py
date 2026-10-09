from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app import jobs
from app.reconciliation import claim_publication, deliver, reconcile_once


@pytest.fixture
def pending(monkeypatch):
    root = Path("data/test-tmp")
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root) as directory:
        monkeypatch.setattr(jobs, "DATABASE_PATH", Path(directory) / "jobs.sqlite3")
        monkeypatch.setattr(jobs, "JOB_UPLOADS", Path(directory) / "uploads")
        yield jobs.job_store.create("file.kml", b"payload").job_id


def publication(job_id):
    with jobs.job_store._connect() as db:
        return dict(db.execute("SELECT * FROM job_publications WHERE job_id=?", (job_id,)).fetchone())


def test_pending_intent_recovered_and_published(pending):
    calls = []
    assert reconcile_once(calls.append) == 1
    assert calls == [pending]
    assert publication(pending)["status"] == "PUBLISHED"
    assert reconcile_once(calls.append) == 0


def test_failure_schedules_backoff_and_recovers(pending):
    now = datetime.now(UTC)
    def unavailable(job_id):
        raise ConnectionError("broker down")
    assert reconcile_once(unavailable, now) == 0
    record = publication(pending)
    assert record["attempt_count"] == 1
    assert record["last_error"]
    assert record["next_attempt_at"] > now.isoformat()
    assert reconcile_once(lambda _: None, now) == 0
    assert reconcile_once(lambda _: None, now + timedelta(seconds=10)) == 1
    assert jobs.job_store.get(pending).status == "QUEUED"
    assert list(jobs.JOB_UPLOADS.iterdir())


def test_concurrent_claims_and_expired_publisher_recovery(pending):
    now = datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim_publication(pending, now), range(8)))
    assert sum(token is not None for token in claims) == 1
    assert reconcile_once(lambda _: None, now) == 0
    assert reconcile_once(lambda _: None, now + timedelta(seconds=61)) == 1


def test_accepted_message_then_crash_republishes_safely(pending):
    now = datetime.now(UTC)
    accepted = []
    def crashed(job_id):
        accepted.append(job_id)
        raise SystemExit("publisher killed before recording success")
    with pytest.raises(SystemExit):
        deliver(pending, crashed, now)
    assert publication(pending)["status"] == "PUBLISHING"
    assert reconcile_once(accepted.append, now + timedelta(seconds=61)) == 1
    assert accepted == [pending, pending]
    assert jobs.job_store.claim(pending) is not None
    assert jobs.job_store.claim(pending) is None


def test_publication_retry_limit(pending):
    with jobs.job_store._connect() as db:
        db.execute("UPDATE job_publications SET attempt_count=8 WHERE job_id=?", (pending,))
    assert reconcile_once(lambda _: pytest.fail("must not publish")) == 0
    assert publication(pending)["status"] == "EXHAUSTED"
    assert jobs.job_store.get(pending).status == "FAILED"
