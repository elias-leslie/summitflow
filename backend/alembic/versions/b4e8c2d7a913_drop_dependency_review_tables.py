"""Drop the dependency review tables; the nightly OSV alert replaces them.

Revision ID: b4e8c2d7a913
Revises: a7d1c3e5f902

The review system logged 2,017 events in a month, none became a task. Both tables were exported as JSONL to
/srv/workspaces/archive/summitflow-dependency-reviews-2026-10-27/ before this migration.
"""

from alembic import op

revision = "b4e8c2d7a913"
down_revision = "a7d1c3e5f902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dependency_review_checks")
    op.execute("DROP TABLE IF EXISTS dependency_review_events")


def downgrade() -> None:
    raise RuntimeError(
        "Cannot restore the dependency review tables: their rows are archived as JSONL in "
        "/srv/workspaces/archive/summitflow-dependency-reviews-2026-10-27/"
    )
