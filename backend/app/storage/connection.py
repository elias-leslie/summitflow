"""Database connection management."""

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
    assert DATABASE_URL is not None, "DATABASE_URL must be set"
    conn = psycopg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


# Import init_schema after defining get_connection to avoid circular import
# This works because the import happens after get_connection is defined
def init_schema() -> None:
    """Initialize database schema.

    This is a re-export for backwards compatibility.
    The actual implementation is in schema.py.
    """
    from .schema import init_schema as _init_schema

    _init_schema()
