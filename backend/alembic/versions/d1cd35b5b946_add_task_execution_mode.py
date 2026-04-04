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


def _existing_task_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("tasks")}


def _existing_task_constraints() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {constraint["name"] for constraint in inspector.get_check_constraints("tasks")}


def upgrade() -> None:
    """Upgrade schema."""
    existing_columns = _existing_task_columns()
    if "execution_mode" not in existing_columns:
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
    if "ck_tasks_execution_mode" not in _existing_task_constraints():
        op.create_check_constraint(
            "ck_tasks_execution_mode",
            "tasks",
            "execution_mode IN ('manual', 'autonomous', 'manual_only')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    if "ck_tasks_execution_mode" in _existing_task_constraints():
        op.drop_constraint("ck_tasks_execution_mode", "tasks", type_="check")
    if "execution_mode" in _existing_task_columns():
        op.drop_column("tasks", "execution_mode")
