"""Fence publication ownership and recover crashed publishers."""
from alembic import op
import sqlalchemy as sa

revision = "0002_publication_leases"
down_revision = "0001_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_publications", sa.Column("claim_token", sa.Text()))
    op.add_column("job_publications", sa.Column("claim_expires_at", sa.Text()))
    op.create_index("ix_publication_lease", "job_publications", ["status", "claim_expires_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrade requires an explicit retention plan.")
