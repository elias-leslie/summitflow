"""Delete rows left behind by retired autonomous and restic-pilot workflows.

- automation_clock_fences: rows for work_pickup, task_generation and
  self_healing. The autonomous pipeline is retired and nothing reads fences.
- maintenance_runs: restic_daily_pilot (140 runs stuck in 'running' after the
  pilot was removed), autonomous_work_pickup, routine_upkeep and
  tool_governance. No code writes these workflow names any more.

Owner approved the data deletion 2026-10-11. Both tables were archived first
with pg_dump -Fc to
backups/table-archives/pre-cleanup-20261011T142716Z.dump (row counts checked
against the live tables).

Downgrade does nothing: restore the rows from that archive with pg_restore if
they are ever needed again.

Revision ID: aa7b8a7f0c76
Revises: 9698cd4e8998
"""

from alembic import op

revision = "aa7b8a7f0c76"
down_revision = "9698cd4e8998"
branch_labels = None
depends_on = None

_RETIRED_FENCE_KEYS = ("work_pickup", "task_generation", "self_healing")
_RETIRED_MAINTENANCE_WORKFLOWS = (
    "restic_daily_pilot",
    "autonomous_work_pickup",
    "routine_upkeep",
    "tool_governance",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute(
        "DELETE FROM automation_clock_fences "
        f"WHERE workflow_key IN ({_quoted(_RETIRED_FENCE_KEYS)})"
    )
    op.execute(
        "DELETE FROM maintenance_runs "
        f"WHERE workflow_name IN ({_quoted(_RETIRED_MAINTENANCE_WORKFLOWS)})"
    )


def downgrade() -> None:
    """No-op; data deletion is owner-approved. Restore from the archive named above."""
