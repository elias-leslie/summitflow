"""archive task_subtask_steps table

Revision ID: d2db0d94066c
Revises: 52f2ce12774b
Create Date: 2026-03-19 14:03:46.505602

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd2db0d94066c'
down_revision: str | Sequence[str] | None = '52f2ce12774b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename task_subtask_steps to archived table (reversible)."""
    op.rename_table("task_subtask_steps", "task_subtask_steps_archived")


def downgrade() -> None:
    """Restore archived steps table."""
    op.rename_table("task_subtask_steps_archived", "task_subtask_steps")
