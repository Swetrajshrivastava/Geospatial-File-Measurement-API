from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from threading import RLock

from app.models import FeatureMeasurement, FileSummary, JobSummary, MeasurementsResponse
from app.processor import ProcessingError, process_upload
from app.repository import ProcessedFile

DATABASE_PATH = Path(os.getenv("JOB_DATABASE_PATH", "data/geospatial_jobs.sqlite3"))
JOB_UPLOADS = Path(os.getenv("JOB_UPLOAD_DIR", "data/job-uploads"))
JOB_WORK = Path(os.getenv("JOB_WORK_DIR", "data/job-work"))
_migration_lock = RLock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class IdempotencyConflict(ValueError):
    pass


class JobStore:
    """SQLite persistence for the in-process background-job prototype."""

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(DATABASE_PATH, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with _migration_lock:
            self._migrate()

    def _migrate(self) -> None:
        from alembic import command
        from alembic.config import Config

        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
            if exists and db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_publication_leases":
                return
        command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")

    def create(self, filename: str, contents: bytes, idempotency_key: str | None = None) -> JobSummary:
        self.initialize()
        fingerprint = hashlib.sha256(Path(filename).suffix.lower().encode() + b"\0" + contents).hexdigest()
        job_id = uuid4().hex
        suffix = Path(filename).suffix.lower()
        JOB_UPLOADS.mkdir(parents=True, exist_ok=True)
        upload_path = JOB_UPLOADS / f"{job_id}{suffix}"
        created_at = _now()
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if idempotency_key is not None:
                    existing = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                    if existing:
                        if existing["payload_fingerprint"] != fingerprint:
                            raise IdempotencyConflict("Idempotency-Key was already used with a different payload.")
                        return self._summary(existing)
                upload_path.write_bytes(contents)
                db.execute("INSERT INTO jobs (id, filename, upload_path, status, created_at, idempotency_key, payload_fingerprint) VALUES (?, ?, ?, 'QUEUED', ?, ?, ?)", (job_id, Path(filename).name, str(upload_path), created_at, idempotency_key, fingerprint))
                db.execute("INSERT INTO job_publications (job_id) VALUES (?)", (job_id,))
        except Exception:
            upload_path.unlink(missing_ok=True)
            raise
        return JobSummary(job_id=job_id, filename=Path(filename).name, status="QUEUED", feature_count=0, processed_count=0, successful_count=0, failed_count=0, progress_percent=0.0, created_at=created_at)

    def get(self, job_id: str) -> JobSummary | None:
        self.initialize()
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._summary(row) if row else None

    def _summary(self, row: sqlite3.Row) -> JobSummary:
        count = row["feature_count"]
        progress = round((row["processed_count"] / count * 100) if count else (100 if row["status"] in {"COMPLETED", "PARTIALLY_FAILED"} else 0), 2)
        return JobSummary(job_id=row["id"], filename=row["filename"], status=row["status"], source_crs=row["source_crs"], feature_count=count, processed_count=row["processed_count"], successful_count=row["successful_count"], failed_count=row["failed_count"], progress_percent=progress, error_message=row["error_message"], created_at=row["created_at"], started_at=row["started_at"], completed_at=row["completed_at"])

    def claim(self, job_id: str) -> tuple[str, str] | None:
        with self._connect() as db:
            claimed = db.execute("UPDATE jobs SET status = 'PROCESSING', started_at = ? WHERE id = ? AND status = 'QUEUED'", (_now(), job_id))
            if claimed.rowcount != 1:
                return None
            row = db.execute("SELECT upload_path, filename FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row["upload_path"], row["filename"]

    def complete(self, job_id: str, processed: ProcessedFile) -> None:
        payload = json.dumps([feature.model_dump(mode="json") for feature in processed.features])
        successful = sum(feature.measurement_status == "COMPLETED" for feature in processed.features)
        # Feature validation/measurement statuses are data outcomes, not worker failures.
        # A parser or infrastructure error is handled by fail(), which marks the job FAILED.
        failed = 0
        status = "COMPLETED"
        with self._connect() as db:
            db.execute("""UPDATE jobs SET status=?, source_crs=?, feature_count=?, processed_count=?, successful_count=?, failed_count=?, completed_at=?, results_json=? WHERE id=?""", (status, processed.summary.crs, len(processed.features), len(processed.features), successful, failed, _now(), payload, job_id))

    def fail(self, job_id: str, message: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET status='FAILED', error_message=?, completed_at=? WHERE id=?", (message, _now(), job_id))

    def fail_publication(self, job_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET status='FAILED', error_message=?, completed_at=? WHERE id=? AND status='QUEUED'", ("Task publication failed; upload retained for diagnosis.", _now(), job_id))
            db.execute("UPDATE job_publications SET status='PENDING', attempt_count=attempt_count+1, last_error=? WHERE job_id=?", ("Task publication failed or outcome uncertain.", job_id))

    def mark_published(self, job_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE job_publications SET status='PUBLISHED', attempt_count=attempt_count+1, published_at=?, last_error=NULL WHERE job_id=?", (_now(), job_id))

    def results(self, job_id: str) -> MeasurementsResponse | None:
        summary = self.get(job_id)
        if summary is None or summary.status not in {"COMPLETED", "PARTIALLY_FAILED"}:
            return None
        with self._connect() as db:
            row = db.execute("SELECT results_json FROM jobs WHERE id=?", (job_id,)).fetchone()
        features = [FeatureMeasurement.model_validate(item) for item in json.loads(row["results_json"] or "[]")]
        file_summary = FileSummary(id=summary.job_id, filename=summary.filename, feature_count=summary.feature_count, crs=summary.source_crs, status=summary.status)
        return MeasurementsResponse(file=file_summary, features=features)


job_store = JobStore()


def process_job(job_id: str) -> None:
    claimed = job_store.claim(job_id)
    if claimed is None:
        return
    upload_path, filename = claimed
    path = Path(upload_path)
    try:
        processed = process_upload(filename, path.read_bytes(), JOB_WORK)
        job_store.complete(job_id, processed)
    except (ProcessingError, OSError) as exc:
        job_store.fail(job_id, str(exc))
    except Exception:
        job_store.fail(job_id, "Processing failed unexpectedly.")
    finally:
        path.unlink(missing_ok=True)
