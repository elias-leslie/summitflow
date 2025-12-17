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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    health_endpoint TEXT DEFAULT '/health',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.commit()


if __name__ == "__main__":
    print("Initializing SummitFlow schema...")
    init_schema()
    print("Done!")
