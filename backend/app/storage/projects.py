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


def find_project_by_cwd(cwd: str) -> dict[str, Any] | None:
    """Find project whose root_path matches the given working directory.

    Checks if cwd starts with any project's root_path.

    Args:
        cwd: Current working directory path

    Returns:
        Project dict with id, name, root_path or None if no match.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Find project where cwd starts with root_path
        # Order by root_path length descending to get most specific match
        cur.execute(
            """
            SELECT id, name, root_path
            FROM projects
            WHERE root_path IS NOT NULL
              AND %s LIKE root_path || '%%'
            ORDER BY LENGTH(root_path) DESC
            LIMIT 1
            """,
            (cwd,),
        )
        row = cur.fetchone()
        if row:
            return {"id": row[0], "name": row[1], "root_path": row[2]}
        return None


def list_projects() -> list[dict[str, Any]]:
    """List all projects.

    Returns:
        List of project dicts with id, name, root_path.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, root_path, created_at
            FROM projects
            ORDER BY created_at
            """
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "root_path": row[2],
                "created_at": row[3],
            }
            for row in cur.fetchall()
        ]
