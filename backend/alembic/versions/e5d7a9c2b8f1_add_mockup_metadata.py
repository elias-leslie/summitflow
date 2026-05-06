"""add mockup metadata

Revision ID: e5d7a9c2b8f1
Revises: b4a8dd2147c2
Create Date: 2026-05-06 09:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5d7a9c2b8f1"
down_revision: str | Sequence[str] | None = "b4a8dd2147c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mockups" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("mockups")}
    if "metadata" not in columns:
        op.add_column(
            "mockups",
            sa.Column(
                "metadata",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mockups" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("mockups")}
    if "metadata" in columns:
        op.drop_column("mockups", "metadata")
