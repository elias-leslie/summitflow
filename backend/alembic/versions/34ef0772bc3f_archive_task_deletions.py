"""archive task deletions

Revision ID: 34ef0772bc3f
Revises: c4a7e8f1b2d3
Create Date: 2026-03-24 00:20:15.495670

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '34ef0772bc3f'
down_revision: str | Sequence[str] | None = 'c4a7e8f1b2d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "task_deletions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("deletion_source", sa.Text(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("deletion_reason", sa.Text(), nullable=True),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "idx_task_deletions_task_id_deleted_at",
        "task_deletions",
        ["task_id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "idx_task_deletions_project_id",
        "task_deletions",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_task_deletions_project_id", table_name="task_deletions")
    op.drop_index("idx_task_deletions_task_id_deleted_at", table_name="task_deletions")
    op.drop_table("task_deletions")
