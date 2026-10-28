"""drop retired autonomous-pipeline keys from agent_configs and the clock-fence table

Revision ID: 6537e645f71c
Revises: bf9a0658177b

The autonomous pipeline (work pickup, routine upkeep/task generation, self-fix and
supervisor loops, quality-gate self-heal, auto-merge) was retired on 2026-10-10, and
Agent Hub no longer registers or dispatches work_pickup/task_generation. Nothing reads
these agent_configs keys any more, so strip them from every project row:

- autonomous_* execution controls, upkeep_*, work_pickup_enabled, task_generation_enabled
- quality_gate_tools/mode/fix_enabled
- claude_enabled, gemini_enabled, default_agent, claude_model, gemini_model and
  component_source (their only accessors had no callers)

The projects.agent_configs column default carried the agent keys, so it becomes '{}'.

automation_clock_fences only accepted work_pickup/task_generation, its fence endpoint is
removed, and it holds no rows (aa7b8a7f0c76 deleted them), so the table is dropped.

Downgrade restores the prior defaults without overwriting any value still present,
the old column default, and the empty table.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6537e645f71c"
down_revision: str | Sequence[str] | None = "bf9a0658177b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RETIRED_KEYS = (
    "autonomous_enabled",
    "autonomous_start_hour",
    "autonomous_end_hour",
    "autonomous_frequency_minutes",
    "autonomous_max_concurrent",
    "autonomous_auto_merge_tiers",
    "autonomous_task_types",
    "autonomous_max_tasks_per_day",
    "autonomous_cooldown_minutes",
    "autonomous_allowed_types",
    "autonomous_external_origins",
    "autonomous_max_self_fix_attempts",
    "autonomous_max_supervisor_attempts",
    "autonomous_max_extensions",
    "autonomous_require_review",
    "upkeep_enabled",
    "upkeep_frequency_minutes",
    "upkeep_batch_limit",
    "work_pickup_enabled",
    "task_generation_enabled",
    "quality_gate_tools",
    "quality_gate_mode",
    "quality_gate_fix_enabled",
    "claude_enabled",
    "gemini_enabled",
    "default_agent",
    "claude_model",
    "gemini_model",
    "component_source",
)

# Prior DEFAULT_AGENT_CONFIG values (autonomous_external_origins had no default).
_PRIOR_DEFAULTS = """{
    "claude_enabled": true,
    "gemini_enabled": true,
    "default_agent": "gemini",
    "component_source": "manual",
    "autonomous_enabled": false,
    "autonomous_start_hour": 0,
    "autonomous_end_hour": 24,
    "autonomous_frequency_minutes": 30,
    "autonomous_max_concurrent": 1,
    "autonomous_auto_merge_tiers": [1],
    "autonomous_task_types": ["auto-generated"],
    "upkeep_enabled": false,
    "upkeep_frequency_minutes": 120,
    "upkeep_batch_limit": 5,
    "work_pickup_enabled": false,
    "task_generation_enabled": true,
    "autonomous_max_tasks_per_day": null,
    "autonomous_cooldown_minutes": 0,
    "autonomous_allowed_types": ["feature", "bug", "task", "refactor", "debt", "regression"],
    "autonomous_max_self_fix_attempts": 3,
    "autonomous_max_supervisor_attempts": 3,
    "autonomous_max_extensions": 3,
    "autonomous_require_review": false,
    "quality_gate_tools": [],
    "quality_gate_mode": "quick",
    "quality_gate_fix_enabled": true
}"""

_PRIOR_COLUMN_DEFAULT = (
    """'{"claude_model": "sonnet", "gemini_model": "gemini-2.5-flash", "default_agent": "gemini", """
    """"claude_enabled": true, "gemini_enabled": true}'::jsonb"""
)


def _key_array() -> str:
    return "ARRAY[" + ", ".join(f"'{key}'" for key in _RETIRED_KEYS) + "]::text[]"


def upgrade() -> None:
    """Strip the retired keys, empty the column default and drop the dead fence table."""
    keys = _key_array()
    op.execute(
        f"""
        UPDATE projects
        SET agent_configs = agent_configs - {keys}
        WHERE agent_configs ?| {keys}
        """
    )
    op.execute("ALTER TABLE projects ALTER COLUMN agent_configs SET DEFAULT '{}'::jsonb")
    op.execute("DROP TABLE IF EXISTS automation_clock_fences")


def downgrade() -> None:
    """Restore the prior defaults under existing values, the column default and the table."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_clock_fences (
            project_id TEXT NOT NULL,
            workflow_key TEXT NOT NULL CHECK (
                workflow_key IN ('work_pickup', 'task_generation')
            ),
            clock_owner TEXT NOT NULL CHECK (clock_owner = 'agent_hub'),
            fence_receipt TEXT NOT NULL UNIQUE,
            fenced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (project_id, workflow_key)
        )
        """
    )
    op.execute(f"ALTER TABLE projects ALTER COLUMN agent_configs SET DEFAULT {_PRIOR_COLUMN_DEFAULT}")
    op.execute(
        f"""
        UPDATE projects
        SET agent_configs = '{_PRIOR_DEFAULTS}'::jsonb || COALESCE(agent_configs, '{{}}'::jsonb)
        """
    )
