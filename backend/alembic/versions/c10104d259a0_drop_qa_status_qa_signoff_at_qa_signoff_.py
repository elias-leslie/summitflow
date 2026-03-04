"""drop qa_status qa_signoff_at qa_signoff_by qa_issues columns from tasks

Revision ID: c10104d259a0
Revises: 3cfe9895dc2a
Create Date: 2026-03-04 10:49:55.970858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c10104d259a0'
down_revision: Union[str, Sequence[str], None] = '3cfe9895dc2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop vestigial QA workflow columns from tasks table.

    These columns were part of a human QA signoff workflow that was never
    used in the autonomous pipeline. Triggers were already dropped in
    migration 088.
    """
    op.drop_column("tasks", "qa_status")
    op.drop_column("tasks", "qa_signoff_at")
    op.drop_column("tasks", "qa_signoff_by")
    op.drop_column("tasks", "qa_issues")


def downgrade() -> None:
    """Restore QA workflow columns."""
    op.add_column("tasks", sa.Column("qa_issues", sa.JSON(), nullable=True))
    op.add_column("tasks", sa.Column("qa_signoff_by", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("qa_signoff_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("qa_status", sa.Text(), nullable=True, server_default="pending"),
    )
