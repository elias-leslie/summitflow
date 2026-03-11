"""maintenance retention and schema alignment

Revision ID: 0143f4557e0e
Revises: a24e1b127505
Create Date: 2026-03-11 09:51:05.393245

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0143f4557e0e"
down_revision: str | Sequence[str] | None = "a24e1b127505"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS capability_id INTEGER")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS feature_id INTEGER")
    op.execute("ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS build_state JSONB DEFAULT '{}'::jsonb")

    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_capability ON tasks(capability_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_feature ON tasks(feature_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_project_status_created "
        "ON notifications(project_id, status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_history_project_started "
        "ON scan_history(project_id, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_backup_sources_enabled_next_run "
        "ON backup_sources(enabled, next_run_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_backups_source_status_created "
        "ON backups(source_id, status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_backups_project_status_completed "
        "ON backups(project_id, status, completed_at DESC)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_backups_project_status_completed")
    op.execute("DROP INDEX IF EXISTS idx_backups_source_status_created")
    op.execute("DROP INDEX IF EXISTS idx_backup_sources_enabled_next_run")
    op.execute("DROP INDEX IF EXISTS idx_scan_history_project_started")
    op.execute("DROP INDEX IF EXISTS idx_notifications_project_status_created")
    op.execute("DROP INDEX IF EXISTS idx_tasks_updated")
    op.execute("DROP INDEX IF EXISTS idx_tasks_feature")
    op.execute("DROP INDEX IF EXISTS idx_tasks_capability")
    op.execute("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS build_state")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS feature_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS capability_id")
