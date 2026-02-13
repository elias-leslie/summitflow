"""drop_expected_output_columns

Drop the expected_output column from task_subtask_steps and
task_acceptance_criteria tables. This field is no longer used
in the application.

Revision ID: a3b7c9e2f410
Revises: d6e4f895f767
Create Date: 2026-02-12 18:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b7c9e2f410"
down_revision: str | Sequence[str] | None = "d6e4f895f767"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop expected_output column from task_subtask_steps (and task_acceptance_criteria if it exists)."""
    op.execute("ALTER TABLE task_subtask_steps DROP COLUMN IF EXISTS expected_output")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'task_acceptance_criteria') THEN
                ALTER TABLE task_acceptance_criteria DROP COLUMN IF EXISTS expected_output;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Re-add expected_output as nullable text columns."""
    op.execute("ALTER TABLE task_subtask_steps ADD COLUMN IF NOT EXISTS expected_output TEXT")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'task_acceptance_criteria') THEN
                ALTER TABLE task_acceptance_criteria ADD COLUMN IF NOT EXISTS expected_output TEXT;
            END IF;
        END $$;
    """)
