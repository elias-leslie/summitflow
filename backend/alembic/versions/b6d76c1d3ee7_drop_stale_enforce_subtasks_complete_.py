"""drop stale enforce_subtasks_complete_before_qa_pass trigger

The trigger referenced NEW.qa_status but the qa_status column was removed
from the tasks table. This caused every task UPDATE to fail with:
  psycopg.errors.UndefinedColumn: record "new" has no field "qa_status"

This blocked all task operations (dispatch, cancel, status changes).
Already dropped in production via direct SQL; this migration documents it.

Revision ID: b6d76c1d3ee7
Revises: c10104d259a0
Create Date: 2026-03-04 20:53:58.424599

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b6d76c1d3ee7'
down_revision: str | Sequence[str] | None = 'c10104d259a0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop stale trigger that referenced removed qa_status column."""
    op.execute("DROP TRIGGER IF EXISTS enforce_subtasks_complete_before_qa_pass ON tasks")
    op.execute("DROP FUNCTION IF EXISTS enforce_subtasks_complete_before_qa_pass()")


def downgrade() -> None:
    """Recreate the trigger (requires qa_status column to exist)."""
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_subtasks_complete_before_qa_pass()
        RETURNS trigger LANGUAGE plpgsql AS $function$
        DECLARE
            incomplete_count INTEGER;
        BEGIN
            IF NEW.qa_status = 'passed' AND (OLD.qa_status IS NULL OR OLD.qa_status != 'passed') THEN
                SELECT COUNT(*) INTO incomplete_count
                FROM task_subtasks
                WHERE task_id = NEW.id AND passes = FALSE;
                IF incomplete_count > 0 THEN
                    RAISE EXCEPTION 'Cannot pass QA with % incomplete subtasks.', incomplete_count;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $function$
    """)
    op.execute("""
        CREATE TRIGGER enforce_subtasks_complete_before_qa_pass
        BEFORE UPDATE ON tasks
        FOR EACH ROW
        EXECUTE FUNCTION enforce_subtasks_complete_before_qa_pass()
    """)
