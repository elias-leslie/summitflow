"""Add durable Agent Hub automation dispatch receipts.

Revision ID: 9ab4d2e6c810
Revises: e82b4cf60a31
Create Date: 2026-09-23 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9ab4d2e6c810"
down_revision: str | Sequence[str] | None = "e82b4cf60a31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE automation_dispatch_receipts (
            run_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            workflow_key TEXT NOT NULL CHECK (
                workflow_key IN ('work_pickup', 'task_generation')
            ),
            definition_version INTEGER NOT NULL CHECK (definition_version > 0),
            profile_revision INTEGER NOT NULL CHECK (profile_revision > 0),
            occurrence_key TEXT NOT NULL,
            trigger TEXT NOT NULL,
            scheduled_for TIMESTAMPTZ NOT NULL,
            request_payload JSONB NOT NULL,
            owner_run_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (
                status IN (
                    'pending', 'queued', 'running', 'succeeded', 'failed',
                    'skipped', 'cancelled'
                )
            ),
            worker_run_id TEXT,
            result JSONB,
            error TEXT,
            completion_reported_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_automation_dispatch_receipts_status_updated "
        "ON automation_dispatch_receipts(status, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_automation_dispatch_receipts_status_updated")
    op.execute("DROP TABLE IF EXISTS automation_dispatch_receipts")
