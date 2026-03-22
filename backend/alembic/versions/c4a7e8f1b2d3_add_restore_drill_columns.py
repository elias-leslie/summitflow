"""add restore drill tracking columns to backup_sources

Add last_drill_at, last_drill_ok, last_drill_backup_id, last_drill_result
columns for tracking infrastructure restore drill results.

Revision ID: c4a7e8f1b2d3
Revises: 63fecd7db0f2
Create Date: 2026-03-22 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a7e8f1b2d3"
down_revision: str | Sequence[str] | None = "63fecd7db0f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE backup_sources
        ADD COLUMN IF NOT EXISTS last_drill_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS last_drill_ok BOOLEAN,
        ADD COLUMN IF NOT EXISTS last_drill_backup_id TEXT,
        ADD COLUMN IF NOT EXISTS last_drill_result JSONB
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE backup_sources
        DROP COLUMN IF EXISTS last_drill_at,
        DROP COLUMN IF EXISTS last_drill_ok,
        DROP COLUMN IF EXISTS last_drill_backup_id,
        DROP COLUMN IF EXISTS last_drill_result
    """)
