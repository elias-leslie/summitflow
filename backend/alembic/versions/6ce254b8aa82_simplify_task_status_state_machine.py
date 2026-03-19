"""simplify task status state machine

Revision ID: 6ce254b8aa82
Revises: b7d4e9f2a1c3
Create Date: 2026-03-19 13:50:30.936415

Remaps 11 task statuses to 5: pending, running, completed, failed, cancelled.
- queue → pending
- paused → pending
- blocked → failed
- ai_reviewing → running
- conflicted → failed
- abandoned → cancelled
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6ce254b8aa82"
down_revision: str | Sequence[str] | None = "b7d4e9f2a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mapping: old_status → new_status
_STATUS_MAP = {
    "queue": "pending",
    "paused": "pending",
    "blocked": "failed",
    "ai_reviewing": "running",
    "conflicted": "failed",
    "abandoned": "cancelled",
}


def upgrade() -> None:
    """Remap removed statuses to simplified set."""
    for old_status, new_status in _STATUS_MAP.items():
        op.execute(
            f"UPDATE tasks SET status = '{new_status}' WHERE status = '{old_status}'"
        )


def downgrade() -> None:
    """No-op: cannot recover original statuses from remapped values."""
    pass
