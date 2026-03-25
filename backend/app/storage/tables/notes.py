"""Notes tables — notes, versions, and format proposals."""

import psycopg


def create_notes_tables(cur: psycopg.Cursor) -> None:
    """Create notes table, versions table, format proposals table, and indexes."""
    # Main notes table
    cur.execute(
        """
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
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_project_scope ON notes(project_scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(pinned) WHERE pinned = TRUE"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_tags ON notes USING GIN(tags)")

    # Version history
    cur.execute(
        """
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
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_versions_note ON note_versions(note_id, version DESC)"
    )

    # Format proposals (background formatting results)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS note_format_proposals (
            id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'complete', 'failed', 'accepted', 'discarded')),
            original_title TEXT NOT NULL DEFAULT '',
            original_content TEXT NOT NULL DEFAULT '',
            proposed_title TEXT,
            proposed_content TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_format_proposals_note ON note_format_proposals(note_id, created_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_format_proposals_pending ON note_format_proposals(status) WHERE status = 'pending'"
    )
