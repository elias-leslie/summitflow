"""add runtime metric samples

Revision ID: 9c82f47a6d31
Revises: e74928ff0001
Create Date: 2026-05-01 13:29:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c82f47a6d31"
down_revision: str | Sequence[str] | None = "e74928ff0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_metric_samples (
            id BIGSERIAL PRIMARY KEY,
            sampled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sample_bucket TIMESTAMPTZ NOT NULL,
            service TEXT NOT NULL,
            display_name TEXT NOT NULL,
            manager TEXT NOT NULL,
            category TEXT NOT NULL,
            state TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            source_name TEXT NOT NULL DEFAULT '',
            cpu_percent DOUBLE PRECISION,
            memory_percent DOUBLE PRECISION,
            memory_used_bytes BIGINT,
            memory_limit_bytes BIGINT,
            raw_mem_usage TEXT,
            net_io TEXT,
            block_io TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(service, sample_bucket)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_metric_samples_service_sampled "
        "ON runtime_metric_samples(service, sampled_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_metric_samples_sampled "
        "ON runtime_metric_samples(sampled_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_metric_samples_manager_category "
        "ON runtime_metric_samples(manager, category, sampled_at DESC)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_runtime_metric_samples_manager_category")
    op.execute("DROP INDEX IF EXISTS idx_runtime_metric_samples_sampled")
    op.execute("DROP INDEX IF EXISTS idx_runtime_metric_samples_service_sampled")
    op.execute("DROP TABLE IF EXISTS runtime_metric_samples")
