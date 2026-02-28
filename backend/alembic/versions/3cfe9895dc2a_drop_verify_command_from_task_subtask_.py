"""drop verify_command from task_subtask_steps

Revision ID: 3cfe9895dc2a
Revises: 56459b1bf358
Create Date: 2026-02-28 16:09:19.672663

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cfe9895dc2a'
down_revision: Union[str, Sequence[str], None] = '56459b1bf358'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop verify_command column from task_subtask_steps."""
    op.execute("ALTER TABLE task_subtask_steps DROP COLUMN IF EXISTS verify_command;")


def downgrade() -> None:
    """Re-add verify_command column."""
    op.add_column(
        "task_subtask_steps",
        sa.Column("verify_command", sa.Text(), nullable=True),
    )
