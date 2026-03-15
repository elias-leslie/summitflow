"""WAL archiving management.

Provides functions to query WAL archiving status, enable, and disable
PostgreSQL WAL archiving via ALTER SYSTEM + pg_reload_conf().

ALTER SYSTEM requires superuser privileges, so these functions use
DATABASE_ADMIN_URL when available (falls back to DATABASE_URL).
"""

from __future__ import annotations

from typing import Any

import psycopg

from ..config import settings
from ..logging_config import get_logger
from ..storage.connection import get_connection

logger = get_logger(__name__)


def _get_admin_url() -> str:
    """Get the admin (superuser) database URL for privileged operations."""
    return settings.database_admin_url or settings.database_url


def _autocommit_execute(*statements: str) -> None:
    """Execute statements outside a transaction with superuser privileges.

    Required for ALTER SYSTEM which cannot run inside a transaction block.
    """
    url = _get_admin_url()
    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        for stmt in statements:
            cur.execute(psycopg.sql.SQL(stmt))


def get_wal_status() -> dict[str, Any]:
    """Query pg_stat_archiver, current LSN, and archive configuration.

    Returns:
        Dict with archive_mode, current_lsn, last_archived_wal, etc.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SHOW archive_mode")
        row = cur.fetchone()
        archive_mode = row[0] if row else "off"

        cur.execute("SHOW archive_command")
        row = cur.fetchone()
        archive_command = row[0] if row else ""

        cur.execute("SELECT pg_current_wal_lsn()::text")
        row = cur.fetchone()
        current_lsn = row[0] if row else "0/0"

        cur.execute("""
            SELECT
                archived_count,
                last_archived_wal,
                last_archived_time,
                failed_count,
                last_failed_wal,
                last_failed_time
            FROM pg_stat_archiver
        """)
        archiver_row = cur.fetchone()

    # Check if archive_mode=on is pending in postgresql.auto.conf.
    # Since archive_mode is context=postmaster, it only takes effect after restart.
    # The app user may lack pg_file_settings access, so try the admin connection.
    pending_restart = False
    admin_url = _get_admin_url()
    try:
        with psycopg.connect(admin_url, autocommit=True) as aconn, aconn.cursor() as acur:
            acur.execute(
                "SELECT setting FROM pg_file_settings "
                "WHERE name = 'archive_mode' AND NOT applied "
                "ORDER BY seqno DESC LIMIT 1"
            )
            row = acur.fetchone()
            if row and row[0] in ("on", "always"):
                pending_restart = True
    except Exception:
        pass  # No admin access — can't detect pending state

    result: dict[str, Any] = {
        "archive_mode": archive_mode,
        "archive_command": archive_command,
        "current_lsn": current_lsn,
        "enabled": archive_mode in ("on", "always"),
        "pending_restart": pending_restart,
    }

    if archiver_row:
        result.update({
            "archived_count": archiver_row[0],
            "last_archived_wal": archiver_row[1],
            "last_archived_time": archiver_row[2].isoformat() if archiver_row[2] else None,
            "failed_count": archiver_row[3],
            "last_failed_wal": archiver_row[4],
            "last_failed_time": archiver_row[5].isoformat() if archiver_row[5] else None,
        })

    # Include archive directory info if accessible
    try:
        from .backup_wal_cleanup import get_wal_archive_info

        archive_info = get_wal_archive_info()
        if archive_info.get("accessible"):
            result["archive_segment_count"] = archive_info["segment_count"]
            result["archive_size_bytes"] = archive_info["total_size_bytes"]
            if archive_info.get("oldest_segment"):
                result["archive_oldest_segment"] = archive_info["oldest_segment"]
            if archive_info.get("newest_segment"):
                result["archive_newest_segment"] = archive_info["newest_segment"]
    except Exception:
        pass  # Archive dir may not be mounted

    return result


def enable_wal_archiving(archive_dir: str = "/var/lib/postgresql/wal-archive") -> dict[str, Any]:
    """Enable WAL archiving via ALTER SYSTEM.

    Sets archive_mode=on and archive_command to copy WALs to the archive dir.
    Requires pg_reload_conf() for archive_command changes.
    Note: archive_mode changes require a PostgreSQL restart to take full effect.

    Args:
        archive_dir: Directory to archive WAL files to

    Returns:
        Status dict with current settings
    """
    archive_command = f"cp %p {archive_dir}/%f"

    _autocommit_execute(
        "ALTER SYSTEM SET archive_mode = 'on'",
        f"ALTER SYSTEM SET archive_command = '{archive_command}'",
        "SELECT pg_reload_conf()",
    )

    logger.info("wal_archiving_enabled", archive_dir=archive_dir)
    return get_wal_status()


def disable_wal_archiving() -> dict[str, Any]:
    """Disable WAL archiving via ALTER SYSTEM.

    Resets archive_command to empty. archive_mode change requires restart.

    Returns:
        Status dict with current settings
    """
    _autocommit_execute(
        "ALTER SYSTEM RESET archive_mode",
        "ALTER SYSTEM SET archive_command = ''",
        "SELECT pg_reload_conf()",
    )

    logger.info("wal_archiving_disabled")
    return get_wal_status()
