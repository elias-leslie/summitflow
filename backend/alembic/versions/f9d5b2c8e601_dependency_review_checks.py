"""Track review check cadence separately from immutable decision events.

Revision ID: f9d5b2c8e601
Revises: e23d71a4c901
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f9d5b2c8e601"
down_revision: str | Sequence[str] | None = "e23d71a4c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE dependency_review_checks (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            entry_path TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (project_id, entry_path)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE dependency_review_checks")
