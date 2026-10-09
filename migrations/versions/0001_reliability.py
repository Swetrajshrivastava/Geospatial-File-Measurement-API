"""Adopt the original jobs table and add reliability metadata without losing rows."""
from alembic import op
import sqlalchemy as sa

revision = "0001_reliability"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, filename TEXT NOT NULL, upload_path TEXT NOT NULL,
        status TEXT NOT NULL, source_crs TEXT, feature_count INTEGER NOT NULL DEFAULT 0,
        processed_count INTEGER NOT NULL DEFAULT 0, successful_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0, error_message TEXT,
        created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, results_json TEXT
    )""")
    for column in (
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("payload_fingerprint", sa.Text()),
        sa.Column("lease_token", sa.Text()),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.Text()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
    ):
        op.add_column("jobs", column)
    op.create_index("uq_jobs_idempotency", "jobs", ["idempotency_key"], unique=True)
    op.create_index("ix_jobs_lease", "jobs", ["status", "lease_expires_at"])
    op.create_table("job_publications",
        sa.Column("job_id", sa.Text(), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.Text()), sa.Column("last_error", sa.Text()),
        sa.Column("published_at", sa.Text()))
    op.create_index("ix_publications_pending", "job_publications", ["status", "next_attempt_at"])
    op.create_table("job_attempts",
        sa.Column("job_id", sa.Text(), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("attempt_number", sa.Integer(), primary_key=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False), sa.Column("finished_at", sa.Text()),
        sa.Column("outcome", sa.Text()), sa.Column("error_message", sa.Text()))


def downgrade() -> None:
    raise RuntimeError("Reliability metadata downgrade requires an explicit data-retention plan.")
