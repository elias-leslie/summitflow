"""Database connection management with connection pooling."""

import logging
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from ..config import DATABASE_URL

logger = logging.getLogger(__name__)

# Module-level connection pool (lazy-initialized)
_pool: ConnectionPool | None = None

# Pool configuration
POOL_MIN_SIZE = 5
POOL_MAX_SIZE = 20


def generate_prefixed_id(prefix: str) -> str:
    """Generate a unique ID with the given prefix.

    Args:
        prefix: ID prefix (e.g., 'task', 'sess', 'notif')

    Returns:
        ID in format "{prefix}-{8_char_uuid}"
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def get_pool() -> ConnectionPool:
    """Get the connection pool, initializing if needed."""
    global _pool
    if _pool is None:
        assert DATABASE_URL is not None, "DATABASE_URL must be set"
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            open=True,
        )
        logger.info("Connection pool initialized (min=%d, max=%d)", POOL_MIN_SIZE, POOL_MAX_SIZE)
    return _pool


def open_pool() -> None:
    """Open the connection pool (for FastAPI lifespan startup)."""
    pool = get_pool()
    if pool.closed:
        pool.open()
        logger.info("Connection pool opened")


def close_pool() -> None:
    """Close the connection pool (for FastAPI lifespan shutdown)."""
    global _pool
    if _pool is not None and not _pool.closed:
        _pool.close()
        logger.info("Connection pool closed")
        _pool = None


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Get a database connection from the pool.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    Connection is automatically returned to pool when context exits.
    """
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


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
