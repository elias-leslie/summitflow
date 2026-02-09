"""Code health tables: code_health_lists."""

import psycopg


def create_code_health_tables(cur: psycopg.Cursor) -> None:
    """Create code health tables and their indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS code_health_lists (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            list_type VARCHAR(20) NOT NULL CHECK (list_type IN ('allow', 'block')),
            category VARCHAR(50) NOT NULL,
            pattern TEXT NOT NULL,
            file_glob TEXT,
            reason TEXT,
            confidence FLOAT DEFAULT 1.0,
            source VARCHAR(50) DEFAULT 'manual',
            created_by VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )

    # Create indexes
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_health_project ON code_health_lists(project_id)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_code_health_type ON code_health_lists(list_type)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_health_category ON code_health_lists(category)"
    )

    # Unique constraint using COALESCE for nullable file_glob
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_code_health_unique
        ON code_health_lists(project_id, list_type, category, pattern, COALESCE(file_glob, ''))
        """
    )
