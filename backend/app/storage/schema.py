"""Database schema initialization.

This module contains the init_schema() function which creates all database tables.
Table creation is delegated to focused modules in the tables/ subdirectory.
"""

import logging

import psycopg

from .connection import get_connection
from .tables import (
    apply_schema_migrations,
    create_agent_tables,
    create_core_tables,
    create_design_tables,
    create_notifications_tables,
    create_push_subscriptions_table,
)

logger = logging.getLogger(__name__)

# PostgreSQL advisory lock ID for schema initialization
# Using a fixed hash to ensure all workers use the same lock
SCHEMA_INIT_LOCK_ID = 1234567890


def init_schema() -> None:
    """Initialize database schema.

    Uses PostgreSQL advisory lock to prevent race conditions when multiple
    workers start simultaneously.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Try to acquire advisory lock (non-blocking)
        cur.execute("SELECT pg_try_advisory_lock(%s)", (SCHEMA_INIT_LOCK_ID,))
        row = cur.fetchone()
        got_lock = row[0] if row else False

        if not got_lock:
            # Another worker is initializing, wait for them to finish
            logger.info("Schema initialization in progress by another worker, waiting...")
            cur.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_INIT_LOCK_ID,))
            # They're done, release our lock and return (schema already initialized)
            cur.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_INIT_LOCK_ID,))
            conn.commit()
            logger.info("Schema initialization completed by another worker")
            return

        try:
            _do_init_schema(conn, cur)
        finally:
            # Release the lock
            cur.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_INIT_LOCK_ID,))
            conn.commit()


def _do_init_schema(conn: psycopg.Connection, cur: psycopg.Cursor) -> None:
    """Actual schema initialization (called with advisory lock held)."""
    # Create tables in order of dependencies
    create_core_tables(cur)
    create_agent_tables(cur)
    create_notifications_tables(cur)
    create_push_subscriptions_table(cur)
    create_design_tables(cur)

    # Apply backward compatibility migrations
    apply_schema_migrations(conn, cur)


if __name__ == "__main__":
    print("Initializing SummitFlow schema...")
    init_schema()
    print("Done!")
