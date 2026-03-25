"""add note versions and format proposals tables

Revision ID: 026023735979
Revises: 8e5fe91e3f55
Create Date: 2026-03-24 23:12:59.460206

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '026023735979'
down_revision: str | Sequence[str] | None = '8e5fe91e3f55'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add note_versions and note_format_proposals tables."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS note_versions (
            id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tags TEXT[] DEFAULT '{}',
            change_source VARCHAR(30) NOT NULL DEFAULT 'manual_edit',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_versions_note ON note_versions(note_id, version DESC)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS note_format_proposals (
            id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'complete', 'failed', 'accepted', 'discarded')),
            original_title TEXT NOT NULL DEFAULT '',
            original_content TEXT NOT NULL DEFAULT '',
            proposed_title TEXT,
            proposed_content TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_format_proposals_note ON note_format_proposals(note_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_format_proposals_pending ON note_format_proposals(status) WHERE status = 'pending'"
    )


def downgrade() -> None:
    """Drop note_versions and note_format_proposals tables."""
    op.drop_table("note_format_proposals")
    op.drop_table("note_versions")
