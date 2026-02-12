"""drop_dead_health_settings_tables

Drop legacy code health scanning tables and dead automation settings column.
These were part of the old code health system that has been superseded by
the unified explorer system.

Tables dropped:
- code_health_lists: Allow/block lists for code health scanning
- project_agent_config: Redundant table (projects.agent_configs JSONB is source of truth)
- scan_states: Per-project scan status tracking
- scan_history: Full scan audit trail

Column dropped:
- projects.automation_settings: Dead idea processing configuration

Revision ID: d6e4f895f767
Revises: 233ad1b1d50d
Create Date: 2026-02-12 17:55:44.233255

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e4f895f767"
down_revision: str | Sequence[str] | None = "233ad1b1d50d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop dead code health tables and automation settings column."""
    # Drop tables (use IF EXISTS for safety)
    op.execute("DROP TABLE IF EXISTS code_health_lists CASCADE")
    op.execute("DROP TABLE IF EXISTS project_agent_config CASCADE")
    op.execute("DROP TABLE IF EXISTS scan_states CASCADE")
    op.execute("DROP TABLE IF EXISTS scan_history CASCADE")

    # Drop automation_settings column from projects
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS automation_settings")


def downgrade() -> None:
    """Restore automation_settings column only (tables not restored)."""
    # Recreate automation_settings column with default
    op.execute(
        """
        ALTER TABLE projects ADD COLUMN automation_settings JSONB DEFAULT
        '{"enabled": false, "primary_agent": "gemini", "cron_expression": "0 3 * * *",
          "schedule_preset": "nightly", "secondary_agent": "claude", "daily_budget_usd": 5.0}'::jsonb
        """
    )

    # Note: Tables are not recreated in downgrade - these are permanently removed.
    # If full restoration is needed, reference the original creation migrations.
