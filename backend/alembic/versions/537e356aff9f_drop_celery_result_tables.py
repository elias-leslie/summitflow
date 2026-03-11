"""drop celery result tables

Revision ID: 537e356aff9f
Revises: 8c443d64b9a7
Create Date: 2026-03-11 12:30:33.541463

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '537e356aff9f'
down_revision: str | Sequence[str] | None = '8c443d64b9a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("celery_tasksetmeta")
    op.drop_table("celery_taskmeta")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "celery_taskmeta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("result", sa.LargeBinary(), nullable=True),
        sa.Column("date_done", sa.DateTime(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("args", sa.LargeBinary(), nullable=True),
        sa.Column("kwargs", sa.LargeBinary(), nullable=True),
        sa.Column("worker", sa.String(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=True),
        sa.Column("queue", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_table(
        "celery_tasksetmeta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("taskset_id", sa.String(), nullable=True),
        sa.Column("result", sa.LargeBinary(), nullable=True),
        sa.Column("date_done", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("taskset_id"),
    )
