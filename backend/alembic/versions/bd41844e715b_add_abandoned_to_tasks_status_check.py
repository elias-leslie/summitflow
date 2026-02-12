"""add_abandoned_to_tasks_status_check

The tasks_status_check constraint was missing 'abandoned' status,
causing st abandon to fail with CheckViolation error.

Revision ID: bd41844e715b
Revises: c1496ead682c
Create Date: 2026-02-11 09:10:41.462347

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bd41844e715b'
down_revision: str | Sequence[str] | None = 'c1496ead682c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# All valid task statuses including 'abandoned'
NEW_STATUSES = (
    "'pending','queue','ready','running','paused','blocked',"
    "'pr_created','ai_reviewing','human_review','needs_review','human_reviewing',"
    "'completed','cancelled','failed','abandoned'"
)

# Previous statuses without 'abandoned'
OLD_STATUSES = (
    "'pending','queue','ready','running','paused','blocked',"
    "'pr_created','ai_reviewing','human_review','needs_review','human_reviewing',"
    "'completed','cancelled','failed'"
)


def upgrade() -> None:
    """Add 'abandoned' to tasks_status_check constraint."""
    op.drop_constraint("tasks_status_check", "tasks", type_="check")
    op.create_check_constraint(
        "tasks_status_check",
        "tasks",
        f"status IN ({NEW_STATUSES})",
    )


def downgrade() -> None:
    """Remove 'abandoned' from tasks_status_check constraint."""
    op.drop_constraint("tasks_status_check", "tasks", type_="check")
    op.create_check_constraint(
        "tasks_status_check",
        "tasks",
        f"status IN ({OLD_STATUSES})",
    )
