"""add agent hub session to collab sessions

Revision ID: e74928ff0001
Revises: 3bd998f79eb7
Create Date: 2026-04-26 11:41:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e74928ff0001"
down_revision: str | Sequence[str] | None = "3bd998f79eb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: the collab_sessions table was removed (design-review feature deleted).

    This migration originally added agent_hub_session_id to collab_sessions, but
    that table is no longer created by the schema and is dropped outright two
    revisions later (b4a8dd2147c2). On a fresh database the old add_column ran
    against a non-existent table and aborted `alembic upgrade head`. The column
    it added is dropped downstream regardless, so the net effect over the full
    chain is zero — neutered to a no-op to keep the revision id valid for any
    database still pinned at it while removing the fresh-DB hazard.
    """


def downgrade() -> None:
    """No-op: paired with the neutered upgrade (collab_sessions no longer exists)."""

