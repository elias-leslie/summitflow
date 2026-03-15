"""backup DR gaps: pending upload status + restore test tracking

Add completed_pending_upload to backups.status CHECK constraint.
Add restore test tracking columns to backup_sources.

Revision ID: b7d4e9f2a1c3
Revises: a8f3b2c1d4e5
Create Date: 2026-03-15 14:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4e9f2a1c3"
down_revision: str | Sequence[str] | None = "a8f3b2c1d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Expand backups.status CHECK to include completed_pending_upload
    op.execute("""
        ALTER TABLE backups DROP CONSTRAINT IF EXISTS backups_status_check
    """)
    op.execute("""
        ALTER TABLE backups ADD CONSTRAINT backups_status_check
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'completed_pending_upload'))
    """)

    # 2. Add restore test tracking columns to backup_sources
    op.execute("""
        ALTER TABLE backup_sources
        ADD COLUMN IF NOT EXISTS last_restore_tested_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS last_restore_test_ok BOOLEAN,
        ADD COLUMN IF NOT EXISTS last_restore_test_error TEXT
    """)


def downgrade() -> None:
    # Remove restore test columns
    op.execute("""
        ALTER TABLE backup_sources
        DROP COLUMN IF EXISTS last_restore_tested_at,
        DROP COLUMN IF EXISTS last_restore_test_ok,
        DROP COLUMN IF EXISTS last_restore_test_error
    """)

    # Revert status CHECK (reclassify any pending_upload records first)
    op.execute("""
        UPDATE backups SET status = 'completed'
        WHERE status = 'completed_pending_upload'
    """)
    op.execute("""
        ALTER TABLE backups DROP CONSTRAINT IF EXISTS backups_status_check
    """)
    op.execute("""
        ALTER TABLE backups ADD CONSTRAINT backups_status_check
        CHECK (status IN ('pending', 'running', 'completed', 'failed'))
    """)
