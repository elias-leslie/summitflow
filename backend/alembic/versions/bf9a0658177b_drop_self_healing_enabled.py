"""drop self_healing_enabled from agent_configs JSONB

Revision ID: bf9a0658177b
Revises: 70b219cea955

The self-healing orchestrator workflow was removed with the autonomous pipeline on 2026-10-10, and its
orphaned summitflow-self-healing Hatchet cron was deleted on 2026-10-28. Nothing reads the flag, so strip
the now-meaningless JSONB key from every project's agent_configs.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bf9a0658177b"
down_revision: str | Sequence[str] | None = "70b219cea955"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Strip self_healing_enabled from existing agent_configs rows."""
    op.execute(
        """
        UPDATE projects
        SET agent_configs = agent_configs - 'self_healing_enabled'
        WHERE agent_configs ? 'self_healing_enabled'
        """
    )


def downgrade() -> None:
    """Restore self_healing_enabled=false (the prior default)."""
    op.execute(
        """
        UPDATE projects
        SET agent_configs = jsonb_set(
            COALESCE(agent_configs, '{}'::jsonb),
            '{self_healing_enabled}',
            'false'::jsonb,
            true
        )
        """
    )
