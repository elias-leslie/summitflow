"""add notes table

Revision ID: 8e5fe91e3f55
Revises: 34ef0772bc3f
Create Date: 2026-03-24 20:10:23.749232

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8e5fe91e3f55'
down_revision: str | Sequence[str] | None = '34ef0772bc3f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create notes table and indexes."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            project_scope TEXT NOT NULL DEFAULT 'global',
            type VARCHAR(10) NOT NULL DEFAULT 'note' CHECK (type IN ('note', 'prompt')),
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tags TEXT[] DEFAULT '{}',
            pinned BOOLEAN DEFAULT FALSE,
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_project_scope ON notes(project_scope)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(pinned) WHERE pinned = TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notes_tags ON notes USING GIN(tags)")


def downgrade() -> None:
    """Drop notes table."""
    op.drop_table("notes")
