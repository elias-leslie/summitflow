"""restore_scan_history_and_scan_states

Restore scan_history and scan_states tables that were incorrectly dropped
in d6e4f895f767. These tables are actively used by the frontend trendline
(ScanTrendLine) and the scan tracking system (explorer_scan_state.py).

Recovered from backup: summitflow-20260211-193242.tar.gz (Feb 11, pre-deletion).

Tables restored:
- scan_history: Full scan audit trail with trigger metadata and metrics
- scan_states: Per-project scan status tracking

Revision ID: f106bdcfac27
Revises: a14ee32465a1
Create Date: 2026-02-17 18:12:48.388037

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f106bdcfac27"
down_revision: str | Sequence[str] | None = "a14ee32465a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recreate scan_history and scan_states tables."""
    # --- scan_states (simple status tracking) ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS scan_states (
            project_id VARCHAR(255) PRIMARY KEY,
            status VARCHAR(50) NOT NULL DEFAULT 'idle',
            current_type VARCHAR(50),
            types_total INTEGER DEFAULT 0,
            types_completed INTEGER DEFAULT 0,
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            error TEXT,
            results JSONB DEFAULT '{}',
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_states_status ON scan_states(status)"
    )
    op.execute(
        "COMMENT ON TABLE scan_states IS "
        "'Persists scan state across backend restarts'"
    )

    # --- scan_history (full audit trail) ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id SERIAL PRIMARY KEY,
            project_id VARCHAR(50) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scan_type VARCHAR(50) NOT NULL,
            triggered_by VARCHAR(50) NOT NULL DEFAULT 'manual',
            triggered_by_session TEXT,
            triggered_by_user TEXT,
            trigger_context JSONB DEFAULT '{}',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            duration_ms INTEGER,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            error_message TEXT,
            metrics JSONB DEFAULT '{}',
            entries_found INTEGER DEFAULT 0,
            entries_saved INTEGER DEFAULT 0,
            previous_scan_id INTEGER REFERENCES scan_history(id),
            metrics_delta JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_history_project_type "
        "ON scan_history(project_id, scan_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_history_triggered_by "
        "ON scan_history(triggered_by)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_history_started_at "
        "ON scan_history(started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scan_history_status "
        "ON scan_history(status) WHERE status = 'running'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_scan_history_unique "
        "ON scan_history(project_id, started_at)"
    )

    # Comments
    op.execute(
        "COMMENT ON TABLE scan_history IS "
        "'Tracks all explorer scan executions with trigger metadata "
        "and metrics for trend visualization'"
    )
    op.execute(
        "COMMENT ON COLUMN scan_history.triggered_by IS "
        "'Source that initiated the scan: manual, refactor_it, "
        "daily_qa_scan, audit_it, celery_beat'"
    )
    op.execute(
        "COMMENT ON COLUMN scan_history.trigger_context IS "
        "'Additional context about the trigger "
        "(phase name, goal, baseline_scan_id, etc.)'"
    )
    op.execute(
        "COMMENT ON COLUMN scan_history.metrics_delta IS "
        "'Computed difference from previous_scan_id metrics "
        "(added, removed, changed counts)'"
    )


def downgrade() -> None:
    """Drop scan_history and scan_states tables."""
    op.execute("DROP TABLE IF EXISTS scan_history CASCADE")
    op.execute("DROP TABLE IF EXISTS scan_states CASCADE")
