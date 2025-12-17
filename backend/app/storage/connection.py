"""Database connection management."""

import os
from contextlib import contextmanager
from typing import Generator

import psycopg


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://portfolio_ai_user:portfolio_ai_dev_2025@localhost:5432/summitflow",
)


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Get a database connection.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    conn = psycopg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def init_schema() -> None:
    """Initialize database schema."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Projects table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    health_endpoint TEXT DEFAULT '/health',
                    frontend_port INTEGER DEFAULT 3000,
                    backend_port INTEGER DEFAULT 8000,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            # Sitemap entries - scoped by project
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sitemap_entries (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    port INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    method VARCHAR(10) DEFAULT 'GET',
                    entry_type VARCHAR(20) NOT NULL,
                    source VARCHAR(50),
                    title TEXT,
                    parent_path TEXT,
                    health_status VARCHAR(20) DEFAULT 'unknown',
                    console_errors INTEGER DEFAULT 0,
                    console_warnings INTEGER DEFAULT 0,
                    http_status INTEGER,
                    response_time_ms INTEGER,
                    last_error_message TEXT,
                    last_checked_at TIMESTAMPTZ,
                    discovered_at TIMESTAMPTZ DEFAULT NOW(),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, port, path, method)
                )
                """
            )

            # Sitemap health history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sitemap_health_history (
                    id SERIAL PRIMARY KEY,
                    sitemap_entry_id INTEGER NOT NULL REFERENCES sitemap_entries(id) ON DELETE CASCADE,
                    checked_at TIMESTAMPTZ NOT NULL,
                    health_status VARCHAR(20),
                    console_errors INTEGER DEFAULT 0,
                    console_warnings INTEGER DEFAULT 0,
                    http_status INTEGER,
                    response_time_ms INTEGER,
                    error_details JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            # Indexes for sitemap_entries
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_project ON sitemap_entries(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_port ON sitemap_entries(port)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_health ON sitemap_entries(health_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_entry_type ON sitemap_entries(entry_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_last_checked ON sitemap_entries(last_checked_at)")

            # Indexes for sitemap_health_history
            cur.execute("CREATE INDEX IF NOT EXISTS idx_health_history_entry ON sitemap_health_history(sitemap_entry_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_health_history_checked ON sitemap_health_history(checked_at)")

            conn.commit()


if __name__ == "__main__":
    print("Initializing SummitFlow schema...")
    init_schema()
    print("Done!")
