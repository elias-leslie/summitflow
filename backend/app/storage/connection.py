"""Database connection management."""

import uuid
from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from ..config import DATABASE_URL


def generate_prefixed_id(prefix: str) -> str:
    """Generate a unique ID with the given prefix.

    Args:
        prefix: ID prefix (e.g., 'task', 'sess', 'notif')

    Returns:
        ID in format "{prefix}-{8_char_uuid}"
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


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
    """Initialize database schema and seed base data.

    This is a re-export for backwards compatibility.
    The actual implementation is in schema.py.
    Also seeds the base design standard if it doesn't exist.
    """
    from .schema import init_schema as _init_schema
    from .seed_design_standards import ensure_base_standard

    _init_schema()
    ensure_base_standard()
