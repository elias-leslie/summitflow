"""drop design review tables

Revision ID: b4a8dd2147c2
Revises: 9c82f47a6d31
Create Date: 2026-05-06 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4a8dd2147c2"
down_revision: str | Sequence[str] | None = "9c82f47a6d31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "collab_connector_pairings",
    "collab_evidence_packets",
    "collab_annotations",
    "collab_participants",
    "collab_audit_events",
    "collab_sessions",
    "route_evidence",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    """Downgrade is intentionally omitted for removed design review tables."""
