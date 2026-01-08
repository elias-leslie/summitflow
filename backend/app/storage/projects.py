"""Project storage - Database operations for projects.

Centralizes project-related database queries.
"""

from __future__ import annotations

from typing import Any

from .connection import get_connection


def get_project_test_config(project_id: str) -> tuple[Any, ...] | None:
    """Get project test configuration from database.

    Args:
        project_id: The project ID to look up

    Returns:
        Tuple of (root_path, test_config) or None if project not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT root_path, test_config
            FROM projects
            WHERE id = %s
            """,
            (project_id,),
        )
        return cur.fetchone()


def project_exists(project_id: str) -> bool:
    """Check if a project exists.

    Args:
        project_id: The project ID to check

    Returns:
        True if project exists, False otherwise.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM projects WHERE id = %s",
            (project_id,),
        )
        return cur.fetchone() is not None


def get_project_root_path(project_id: str) -> str | None:
    """Get project root path.

    Args:
        project_id: The project ID

    Returns:
        Root path string or None if project not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_all_project_root_paths() -> list[str]:
    """Get all project root paths.

    Returns:
        List of root path strings for all registered projects.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE root_path IS NOT NULL")
        return [row[0] for row in cur.fetchall()]
