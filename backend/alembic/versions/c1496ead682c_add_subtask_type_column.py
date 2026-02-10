"""add_subtask_type_column

Revision ID: c1496ead682c
Revises: 1c2176c7fa7a
Create Date: 2026-02-09 21:11:45.203094

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1496ead682c'
down_revision: Union[str, Sequence[str], None] = '1c2176c7fa7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add subtask_type column for agent routing."""
    op.execute(
        "ALTER TABLE task_subtasks ADD COLUMN subtask_type TEXT"
    )


def downgrade() -> None:
    """Remove subtask_type column."""
    op.execute(
        "ALTER TABLE task_subtasks DROP COLUMN IF EXISTS subtask_type"
    )
