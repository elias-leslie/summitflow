"""drop enforce_steps_complete trigger — steps layer archived

The enforce_steps_complete_before_subtask_pass trigger references a
'status' column that does not exist on task_subtask_steps, causing
SQL errors when the autonomous pipeline marks subtasks as passed.
The steps layer has been archived; this trigger is dead code.

Revision ID: 63fecd7db0f2
Revises: d2db0d94066c
Create Date: 2026-03-19 17:53:11.737508

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '63fecd7db0f2'
down_revision: str | Sequence[str] | None = 'd2db0d94066c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS enforce_steps_complete_before_subtask_pass ON task_subtasks"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS enforce_steps_complete_before_subtask_pass()"
    )


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_steps_complete_before_subtask_pass()
        RETURNS trigger LANGUAGE plpgsql AS $function$
        DECLARE
            incomplete_steps INTEGER;
        BEGIN
            IF NEW.passes = TRUE AND (OLD.passes IS NULL OR OLD.passes = FALSE) THEN
                SELECT COUNT(*) INTO incomplete_steps
                FROM task_subtask_steps
                WHERE subtask_id = NEW.id
                  AND passes = FALSE
                  AND (status IS NULL OR status != 'plan_defect');
                IF incomplete_steps > 0 THEN
                    RAISE EXCEPTION 'Cannot pass subtask % with % incomplete steps.',
                        NEW.subtask_id, incomplete_steps;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $function$
    """)
    op.execute("""
        CREATE TRIGGER enforce_steps_complete_before_subtask_pass
        BEFORE UPDATE ON task_subtasks
        FOR EACH ROW
        EXECUTE FUNCTION enforce_steps_complete_before_subtask_pass()
    """)
