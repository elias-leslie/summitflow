"""Record owner-approved project retirement independently of repo manifests.

Revision ID: a71e0c6d2f94
Revises: f9d5b2c8e601
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a71e0c6d2f94"
down_revision: str | Sequence[str] | None = "f9d5b2c8e601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_retirement_decisions (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            owner_email TEXT NOT NULL,
            reason TEXT NOT NULL CHECK (length(trim(reason)) >= 10),
            approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_lifecycle_events (
            id BIGSERIAL PRIMARY KEY,
            project_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('retired', 'reactivated')),
            owner_email TEXT NOT NULL,
            reason TEXT,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "ALTER TABLE project_lifecycle_events "
        "DROP CONSTRAINT IF EXISTS project_lifecycle_events_project_id_fkey"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_project_lifecycle_events_project_id "
        "ON project_lifecycle_events (project_id, id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_lifecycle_events")
    op.execute("DROP TABLE IF EXISTS project_retirement_decisions")
