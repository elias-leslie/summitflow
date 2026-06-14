"""Add cumulative design asset votes.

Revision ID: e1a2b3c4d5f6
Revises: d4a7e9b1c602
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1a2b3c4d5f6"
down_revision: str | Sequence[str] | None = "d4a7e9b1c602"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "design_asset_votes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("design_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vote", sa.String(length=10), nullable=False),
        sa.Column("voter_email", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_check_constraint(
        "ck_design_asset_votes_vote",
        "design_asset_votes",
        "vote IN ('up', 'down')",
    )
    op.create_index("idx_design_asset_votes_asset", "design_asset_votes", ["asset_id"])
    op.create_index("idx_design_asset_votes_vote", "design_asset_votes", ["asset_id", "vote"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_design_asset_votes_vote", table_name="design_asset_votes")
    op.drop_index("idx_design_asset_votes_asset", table_name="design_asset_votes")
    op.drop_constraint("ck_design_asset_votes_vote", "design_asset_votes", type_="check")
    op.drop_table("design_asset_votes")
