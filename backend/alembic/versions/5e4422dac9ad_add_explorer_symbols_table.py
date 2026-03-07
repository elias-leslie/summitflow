"""add explorer symbols table

Revision ID: 5e4422dac9ad
Revises: b6d76c1d3ee7
Create Date: 2026-03-06 19:32:44.191166

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e4422dac9ad"
down_revision: str | Sequence[str] | None = "b6d76c1d3ee7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "explorer_symbols",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("symbol_id", sa.String(), nullable=False),
        sa.Column("qualified_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("byte_offset", sa.Integer(), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("keywords", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "symbol_id", name="explorer_symbols_project_symbol_id_key"),
    )
    op.create_index(
        "idx_explorer_symbols_project_file",
        "explorer_symbols",
        ["project_id", "file_path"],
    )
    op.create_index(
        "idx_explorer_symbols_project_language_kind",
        "explorer_symbols",
        ["project_id", "language", "kind"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_explorer_symbols_project_language_kind", table_name="explorer_symbols")
    op.drop_index("idx_explorer_symbols_project_file", table_name="explorer_symbols")
    op.drop_table("explorer_symbols")
