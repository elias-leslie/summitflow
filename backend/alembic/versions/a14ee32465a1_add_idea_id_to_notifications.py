"""add idea_id to notifications

Revision ID: a14ee32465a1
Revises: a3b7c9e2f410
Create Date: 2026-02-14 21:09:20.178714

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a14ee32465a1'
down_revision: str | Sequence[str] | None = 'a3b7c9e2f410'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("notifications", sa.Column("idea_id", sa.Text(), nullable=True))
    op.create_index("idx_notification_idea", "notifications", ["idea_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_notification_idea", table_name="notifications")
    op.drop_column("notifications", "idea_id")
