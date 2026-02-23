"""add conflict_info and merge_sha to tasks

Add conflict_info JSONB column for structured merge conflict data
and merge_sha TEXT column for tracking the merge commit SHA.

Revision ID: 52bde0e4709d
Revises: a0fe725f823f
Create Date: 2026-02-23 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "52bde0e4709d"
down_revision: str | Sequence[str] | None = "a0fe725f823f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add conflict_info JSONB and merge_sha TEXT to tasks table."""
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS conflict_info JSONB")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS merge_sha TEXT")

    # Add 'conflicted' to the status check constraint if it exists
    # First check and drop the old constraint, then add the new one
    op.execute("""
        DO $$
        BEGIN
            -- Drop existing status constraint if it exists
            ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
            -- Add updated constraint with 'conflicted' status
            ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
                CHECK (status IN (
                    'pending', 'queue', 'running', 'paused', 'failed',
                    'blocked', 'ai_reviewing', 'completed', 'cancelled',
                    'abandoned', 'conflicted'
                ));
        EXCEPTION WHEN OTHERS THEN
            -- Constraint may not exist, that's fine
            NULL;
        END $$;
    """)


def downgrade() -> None:
    """Remove conflict_info and merge_sha from tasks table."""
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS conflict_info")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS merge_sha")

    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
            ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
                CHECK (status IN (
                    'pending', 'queue', 'running', 'paused', 'failed',
                    'blocked', 'ai_reviewing', 'completed', 'cancelled',
                    'abandoned'
                ));
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$;
    """)
