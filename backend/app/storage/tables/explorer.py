"""Explorer-related table bootstrap for test schema initialization."""

import psycopg


def create_explorer_tables(cur: psycopg.Cursor) -> None:
    """Create explorer precision-retrieval tables and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS explorer_symbols (
            id BIGSERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            symbol_id TEXT NOT NULL,
            qualified_name TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            signature TEXT NOT NULL,
            language TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            byte_offset INTEGER NOT NULL,
            byte_length INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            summary TEXT,
            keywords TEXT[] NOT NULL DEFAULT '{}'::text[],
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(project_id, symbol_id)
        )
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_explorer_symbols_project_file
        ON explorer_symbols(project_id, file_path)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_explorer_symbols_project_language_kind
        ON explorer_symbols(project_id, language, kind)
        """
    )
