"""maintenance observability and retention hardening

Revision ID: fd955094f350
Revises: 0143f4557e0e
Create Date: 2026-03-11 10:20:56.681247

"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "fd955094f350"
down_revision: str | Sequence[str] | None = "0143f4557e0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_runs (
            id BIGSERIAL PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            duration_ms INTEGER,
            rows_cleaned INTEGER NOT NULL DEFAULT 0,
            summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_maintenance_runs_workflow_started "
        "ON maintenance_runs(workflow_name, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_maintenance_runs_status_started "
        "ON maintenance_runs(status, started_at DESC)"
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_events_trace_timestamp ON events(trace_id, "timestamp" ASC)'
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_qcr_project_created "
        "ON quality_check_results(project_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_qcr_project_type_created "
        "ON quality_check_results(project_id, check_type, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_qa_issues_project_status_detected "
        "ON qa_issues(project_id, status, last_detected_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_backups_project_event_time "
        "ON backups(project_id, COALESCE(completed_at, created_at) DESC) "
        "WHERE status IN ('completed', 'failed')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_backups_project_event_time")
    op.execute("DROP INDEX IF EXISTS idx_qa_issues_project_status_detected")
    op.execute("DROP INDEX IF EXISTS idx_qcr_project_type_created")
    op.execute("DROP INDEX IF EXISTS idx_qcr_project_created")
    op.execute("DROP INDEX IF EXISTS idx_events_trace_timestamp")
    op.execute("DROP INDEX IF EXISTS idx_maintenance_runs_status_started")
    op.execute("DROP INDEX IF EXISTS idx_maintenance_runs_workflow_started")
    op.execute("DROP TABLE IF EXISTS maintenance_runs")
