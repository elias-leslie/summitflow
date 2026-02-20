"""drop push_subscriptions table

Drop the push_subscriptions table as part of the Johnny Mobility Loop Phase 1
cleanup. Push notification subscriptions are now managed by Agent Hub.

Revision ID: a0fe725f823f
Revises: bc72fec32fda
Create Date: 2026-02-19 23:00:04.655957

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a0fe725f823f"
down_revision: str | Sequence[str] | None = "bc72fec32fda"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop push_subscriptions table and its indexes."""
    op.execute("DROP TABLE IF EXISTS push_subscriptions CASCADE")


def downgrade() -> None:
    """Recreate push_subscriptions table with original schema."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id TEXT PRIMARY KEY,
            user_email TEXT,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh_key TEXT NOT NULL,
            auth_key TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            last_used_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_push_sub_user_email ON push_subscriptions(user_email)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_push_sub_endpoint ON push_subscriptions(endpoint)"
    )
