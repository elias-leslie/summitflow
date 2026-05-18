"""drop autonomous_auto_merge_enabled from agent_configs JSONB

Revision ID: b8d2f4a91c33
Revises: a9c4e1b7d2e8
Create Date: 2026-05-18 09:00:00.000000

Auto-merge has been retired alongside the task-branch ceremony; the
autonomous pipeline now commits direct to main and never invokes a
merge_and_cleanup workflow. Strip the now-meaningless JSONB key from
every project's agent_configs.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d2f4a91c33"
down_revision: str | Sequence[str] | None = "a9c4e1b7d2e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Strip autonomous_auto_merge_enabled from existing agent_configs rows."""
    op.execute(
        """
        UPDATE projects
        SET agent_configs = agent_configs - 'autonomous_auto_merge_enabled'
        WHERE agent_configs ? 'autonomous_auto_merge_enabled'
        """
    )


def downgrade() -> None:
    """Restore autonomous_auto_merge_enabled=true (the prior default)."""
    op.execute(
        """
        UPDATE projects
        SET agent_configs = jsonb_set(
            COALESCE(agent_configs, '{}'::jsonb),
            '{autonomous_auto_merge_enabled}',
            'true'::jsonb,
            true
        )
        """
    )
