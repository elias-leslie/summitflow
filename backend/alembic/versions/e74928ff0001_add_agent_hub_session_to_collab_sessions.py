"""add agent hub session to collab sessions

Revision ID: e74928ff0001
Revises: 3bd998f79eb7
Create Date: 2026-04-26 11:41:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e74928ff0001"
down_revision: str | Sequence[str] | None = "3bd998f79eb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "collab_sessions",
        sa.Column("agent_hub_session_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_collab_sessions_agent_hub_session",
        "collab_sessions",
        ["agent_hub_session_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "idx_collab_sessions_agent_hub_session",
        table_name="collab_sessions",
    )
    op.drop_column("collab_sessions", "agent_hub_session_id")

