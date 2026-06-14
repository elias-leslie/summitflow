"""Add cumulative UI mockup votes.

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2b3c4d5e6a7"
down_revision: str | Sequence[str] | None = "e1a2b3c4d5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "mockup_votes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "mockup_id",
            sa.Integer(),
            sa.ForeignKey("mockups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vote", sa.String(length=10), nullable=False),
        sa.Column("voter_email", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_check_constraint(
        "ck_mockup_votes_vote",
        "mockup_votes",
        "vote IN ('up', 'down')",
    )
    op.create_index("idx_mockup_votes_mockup", "mockup_votes", ["mockup_id"])
    op.create_index("idx_mockup_votes_vote", "mockup_votes", ["mockup_id", "vote"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_mockup_votes_vote", table_name="mockup_votes")
    op.drop_index("idx_mockup_votes_mockup", table_name="mockup_votes")
    op.drop_constraint("ck_mockup_votes_vote", "mockup_votes", type_="check")
    op.drop_table("mockup_votes")
