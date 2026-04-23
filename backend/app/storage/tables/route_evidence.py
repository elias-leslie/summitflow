"""Route-evidence table bootstrap for review-overlay persistence."""

import psycopg


def create_route_evidence_tables(cur: psycopg.Cursor) -> None:
    """Create route_evidence table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS route_evidence (
            id BIGSERIAL PRIMARY KEY,
            evidence_id TEXT NOT NULL UNIQUE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            page_key TEXT NOT NULL,
            page_url_snapshot TEXT,
            comment TEXT NOT NULL,
            selector TEXT,
            anchor JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by_kind TEXT NOT NULL DEFAULT 'user',
            created_by_display TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_route_evidence_project_page_created"
        " ON route_evidence(project_id, page_key, created_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_route_evidence_project_created"
        " ON route_evidence(project_id, created_at DESC)"
    )
