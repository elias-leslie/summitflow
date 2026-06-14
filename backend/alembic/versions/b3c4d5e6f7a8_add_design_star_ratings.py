"""Add Design Studio star ratings.

Revision ID: b3c4d5e6f7a8
Revises: f2b3c4d5e6a7
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "f2b3c4d5e6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "design_asset_ratings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("design_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("voter_key", sa.Text(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_design_asset_ratings_rating"),
        sa.UniqueConstraint("asset_id", "voter_key", name="uq_design_asset_ratings_voter"),
    )
    op.create_index("idx_design_asset_ratings_asset", "design_asset_ratings", ["asset_id"])
    op.create_index("idx_design_asset_ratings_rating", "design_asset_ratings", ["asset_id", "rating"])

    op.create_table(
        "mockup_ratings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "mockup_id",
            sa.Integer(),
            sa.ForeignKey("mockups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("voter_key", sa.Text(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_mockup_ratings_rating"),
        sa.UniqueConstraint("mockup_id", "voter_key", name="uq_mockup_ratings_voter"),
    )
    op.create_index("idx_mockup_ratings_mockup", "mockup_ratings", ["mockup_id"])
    op.create_index("idx_mockup_ratings_rating", "mockup_ratings", ["mockup_id", "rating"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_mockup_ratings_rating", table_name="mockup_ratings")
    op.drop_index("idx_mockup_ratings_mockup", table_name="mockup_ratings")
    op.drop_table("mockup_ratings")
    op.drop_index("idx_design_asset_ratings_rating", table_name="design_asset_ratings")
    op.drop_index("idx_design_asset_ratings_asset", table_name="design_asset_ratings")
    op.drop_table("design_asset_ratings")
