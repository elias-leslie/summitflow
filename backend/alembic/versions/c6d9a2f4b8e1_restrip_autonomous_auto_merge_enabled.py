"""restrip retired autonomous auto-merge flag

Revision ID: c6d9a2f4b8e1
Revises: b8d2f4a91c33
Create Date: 2026-05-19 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6d9a2f4b8e1"
down_revision: str | Sequence[str] | None = "b8d2f4a91c33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the retired flag from project JSONB config rows."""
    op.execute(
        """
        UPDATE projects
        SET agent_configs = agent_configs - 'autonomous_auto_merge_enabled'
        WHERE agent_configs ? 'autonomous_auto_merge_enabled'
        """
    )


def downgrade() -> None:
    """No-op: the retired flag should not be restored."""
