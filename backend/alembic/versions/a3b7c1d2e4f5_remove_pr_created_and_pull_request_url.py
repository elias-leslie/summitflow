"""remove pr_created status and pull_request_url column

Solo dev + agents workflow — no CI/CD/PR review pipeline.
Agents work on worktree branches and merge directly.
The pr_created status and pull_request_url column are unused.

Revision ID: a3b7c1d2e4f5
Revises: f106bdcfac27
Create Date: 2026-02-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3b7c1d2e4f5'
down_revision: str | Sequence[str] | None = 'f106bdcfac27'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Statuses without pr_created
NEW_STATUSES = (
    "'pending','queue','ready','running','paused','blocked',"
    "'ai_reviewing','human_review','needs_review','human_reviewing',"
    "'completed','cancelled','failed','abandoned'"
)

# Previous statuses with pr_created
OLD_STATUSES = (
    "'pending','queue','ready','running','paused','blocked',"
    "'pr_created','ai_reviewing','human_review','needs_review','human_reviewing',"
    "'completed','cancelled','failed','abandoned'"
)


def upgrade() -> None:
    """Drop pull_request_url column and remove pr_created from status check."""
    # Drop the column
    op.drop_column("tasks", "pull_request_url")

    # Replace status check constraint without pr_created
    op.drop_constraint("tasks_status_check", "tasks", type_="check")
    op.create_check_constraint(
        "tasks_status_check",
        "tasks",
        f"status IN ({NEW_STATUSES})",
    )


def downgrade() -> None:
    """Restore pull_request_url column and pr_created status."""
    # Restore column
    op.add_column("tasks", sa.Column("pull_request_url", sa.Text(), nullable=True))

    # Restore old status check constraint with pr_created
    op.drop_constraint("tasks_status_check", "tasks", type_="check")
    op.create_check_constraint(
        "tasks_status_check",
        "tasks",
        f"status IN ({OLD_STATUSES})",
    )
