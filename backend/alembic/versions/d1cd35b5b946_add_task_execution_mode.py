"""add task execution mode

Revision ID: d1cd35b5b946
Revises: 5e4422dac9ad
Create Date: 2026-03-07 08:44:57.309367

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1cd35b5b946'
down_revision: str | Sequence[str] | None = '5e4422dac9ad'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tasks",
        sa.Column(
            "execution_mode",
            sa.String(length=20),
            nullable=False,
            server_default="manual",
        ),
    )
    op.execute(
        """
        UPDATE tasks
        SET execution_mode = CASE
            WHEN autonomous IS TRUE THEN 'autonomous'
            ELSE 'manual'
        END
        """
    )
    op.create_check_constraint(
        "ck_tasks_execution_mode",
        "tasks",
        "execution_mode IN ('manual', 'autonomous', 'manual_only')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_tasks_execution_mode", "tasks", type_="check")
    op.drop_column("tasks", "execution_mode")
