"""Downsample historical runtime metrics to the solo-operator policy.

Revision ID: c935fa8c0398
Revises: c5d6e7f8a9b0
Create Date: 2026-07-12 18:29:07.405680

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c935fa8c0398"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep two weeks at one representative sample per service/five minutes."""
    op.execute(
        """
        DELETE FROM runtime_metric_samples
        WHERE sampled_at < NOW() - INTERVAL '14 days'
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        service,
                        FLOOR(EXTRACT(EPOCH FROM sampled_at) / 300)
                    ORDER BY sampled_at DESC, id DESC
                ) AS sample_rank
            FROM runtime_metric_samples
            WHERE sampled_at < NOW() - INTERVAL '10 minutes'
        )
        DELETE FROM runtime_metric_samples AS samples
        USING ranked
        WHERE samples.id = ranked.id
          AND ranked.sample_rank > 1
        """
    )

    # DELETE frees pages for reuse but does not return this previously 1.29 GB
    # diagnostic table to the host. The deploy migration is the one controlled
    # maintenance window where an exclusive rewrite is acceptable.
    with op.get_context().autocommit_block():
        op.execute("VACUUM (FULL, ANALYZE) runtime_metric_samples")


def downgrade() -> None:
    """Historical samples removed by retention cannot be reconstructed."""
