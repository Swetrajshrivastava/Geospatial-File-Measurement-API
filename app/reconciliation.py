"""Leased publication outbox. Never processes geometry or deletes uploads."""
from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.jobs import job_store

logger = logging.getLogger(__name__)
LEASE_SECONDS = 60
MAX_ATTEMPTS = 8


def claim_publication(job_id: str, now: datetime) -> str | None:
    token = uuid4().hex
    with job_store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT p.*, j.status AS job_status, j.error_message FROM job_publications p JOIN jobs j ON j.id=p.job_id WHERE p.job_id=?", (job_id,)).fetchone()
        if not row or row["job_status"] not in {"QUEUED", "FAILED"}:
            return None
        if row["job_status"] == "FAILED" and row["error_message"] != "Task publication failed; upload retained for diagnosis.":
            return None
        due = (row["status"] == "PENDING" and (row["next_attempt_at"] is None or row["next_attempt_at"] <= now.isoformat())) or (row["status"] == "PUBLISHING" and row["claim_expires_at"] <= now.isoformat())
        if not due:
            return None
        if row["attempt_count"] >= MAX_ATTEMPTS:
            db.execute("UPDATE job_publications SET status='EXHAUSTED', claim_token=NULL WHERE job_id=?", (job_id,))
            db.execute("UPDATE jobs SET status='FAILED', error_message='Publication retry limit reached.', completed_at=? WHERE id=? AND status='QUEUED'", (now.isoformat(), job_id))
            return None
        db.execute("UPDATE job_publications SET status='PUBLISHING', claim_token=?, claim_expires_at=?, attempt_count=attempt_count+1 WHERE job_id=?", (token, (now + timedelta(seconds=LEASE_SECONDS)).isoformat(), job_id))
        db.execute("UPDATE jobs SET status='QUEUED', error_message=NULL, completed_at=NULL WHERE id=? AND status='FAILED'", (job_id,))
    return token


def deliver(job_id: str, publish: Callable[[str], None], now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    token = claim_publication(job_id, now)
    if token is None:
        return False
    try:
        publish(job_id)
    except Exception:
        with job_store._connect() as db:
            row = db.execute("SELECT attempt_count FROM job_publications WHERE job_id=? AND claim_token=?", (job_id, token)).fetchone()
            if row:
                delay = min(300, 2 ** row["attempt_count"])
                changed = db.execute("UPDATE job_publications SET status='PENDING', next_attempt_at=?, last_error='Publication failed or uncertain.', claim_token=NULL, claim_expires_at=NULL WHERE job_id=? AND claim_token=?", ((now + timedelta(seconds=delay)).isoformat(), job_id, token))
                if changed.rowcount:
                    db.execute("UPDATE jobs SET status='FAILED', error_message='Task publication failed; upload retained for diagnosis.', completed_at=? WHERE id=? AND status='QUEUED'", (now.isoformat(), job_id))
        raise
    with job_store._connect() as db:
        db.execute("UPDATE job_publications SET status='PUBLISHED', published_at=?, next_attempt_at=NULL, last_error=NULL, claim_token=NULL, claim_expires_at=NULL WHERE job_id=? AND claim_token=?", (now.isoformat(), job_id, token))
    return True


def reconcile_once(publish: Callable[[str], None], now: datetime | None = None, limit: int = 100) -> int:
    job_store.initialize()
    now = now or datetime.now(UTC)
    with job_store._connect() as db:
        rows = db.execute("SELECT job_id FROM job_publications WHERE (status='PENDING' AND (next_attempt_at IS NULL OR next_attempt_at<=?)) OR (status='PUBLISHING' AND claim_expires_at<=?) ORDER BY job_id LIMIT ?", (now.isoformat(), now.isoformat(), limit)).fetchall()
    delivered = 0
    for row in rows:
        try:
            delivered += deliver(row["job_id"], publish, now)
        except Exception:
            logger.warning("Publication failed for job %s; retry scheduled", row["job_id"])
    return delivered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    from app.main import publish_job

    logging.basicConfig(level=logging.INFO)
    while True:
        reconcile_once(publish_job)
        if args.once:
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
