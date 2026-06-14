"""Add Design Studio comments.

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "design_asset_comments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("design_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_email", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("length(trim(body)) > 0", name="ck_design_asset_comments_body"),
    )
    op.create_index("idx_design_asset_comments_asset", "design_asset_comments", ["asset_id"])
    op.create_index("idx_design_asset_comments_created", "design_asset_comments", ["asset_id", "created_at"])

    op.create_table(
        "mockup_comments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "mockup_id",
            sa.Integer(),
            sa.ForeignKey("mockups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_email", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("length(trim(body)) > 0", name="ck_mockup_comments_body"),
    )
    op.create_index("idx_mockup_comments_mockup", "mockup_comments", ["mockup_id"])
    op.create_index("idx_mockup_comments_created", "mockup_comments", ["mockup_id", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_mockup_comments_created", table_name="mockup_comments")
    op.drop_index("idx_mockup_comments_mockup", table_name="mockup_comments")
    op.drop_table("mockup_comments")
    op.drop_index("idx_design_asset_comments_created", table_name="design_asset_comments")
    op.drop_index("idx_design_asset_comments_asset", table_name="design_asset_comments")
    op.drop_table("design_asset_comments")
