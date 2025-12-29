"""Database connection management for Terminal Service."""

from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from ..config import DATABASE_URL


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Get a database connection.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    assert DATABASE_URL, "DATABASE_URL must be set"
    conn = psycopg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()
