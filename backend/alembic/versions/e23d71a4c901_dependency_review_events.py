"""Record revisioned dependency evidence and decisions.

Revision ID: e23d71a4c901
Revises: b81f04c7a22d
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e23d71a4c901"
down_revision: str | Sequence[str] | None = "b81f04c7a22d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE dependency_review_events (
            id BIGSERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            entry_path TEXT NOT NULL,
            revision INTEGER NOT NULL,
            evidence_hash TEXT NOT NULL,
            evidence JSONB NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('pending', 'update', 'hold', 'investigate')),
            recommended_version TEXT,
            rationale TEXT,
            task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (project_id, entry_path, revision)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_dependency_review_events_latest "
        "ON dependency_review_events(project_id, entry_path, revision DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE dependency_review_events")
