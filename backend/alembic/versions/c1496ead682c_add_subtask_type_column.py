"""add_subtask_type_column

Revision ID: c1496ead682c
Revises: 1c2176c7fa7a
Create Date: 2026-02-09 21:11:45.203094

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1496ead682c'
down_revision: str | Sequence[str] | None = '1c2176c7fa7a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_task_subtask_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("task_subtasks")}


def upgrade() -> None:
    """Add subtask_type column for agent routing."""
    if "subtask_type" in _existing_task_subtask_columns():
        return
    op.execute("ALTER TABLE task_subtasks ADD COLUMN subtask_type TEXT")


def downgrade() -> None:
    """Remove subtask_type column."""
    op.execute("ALTER TABLE task_subtasks DROP COLUMN IF EXISTS subtask_type")
