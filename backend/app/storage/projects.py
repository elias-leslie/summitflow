"""Project storage - Database operations for projects.

Centralizes project-related database queries.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .connection import get_connection

logger = logging.getLogger(__name__)


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


def build_project_env(project_id: str | None) -> dict[str, str]:
    """Build environment dict with the correct project venv on PATH.

    Single source of truth for subprocess environment in verification.
    Resolves the main repo's venv from project_id (handles worktrees
    since worktrees don't have their own .venv).
    """
    env = os.environ.copy()
    if not project_id:
        return env

    main_repo = get_project_root_path(project_id)
    if not main_repo:
        return env

    candidates = [
        Path(main_repo) / "backend" / ".venv",
        Path(main_repo) / ".venv",
    ]
    for venv_path in candidates:
        if (venv_path / "bin" / "python").exists():
            venv_bin = str(venv_path / "bin")
            env["VIRTUAL_ENV"] = str(venv_path)
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
            env.pop("PYTHONHOME", None)
            logger.info("resolved_project_venv: venv=%s project_id=%s", venv_path, project_id)
            return env

    logger.debug("no_venv_found: project_id=%s main_repo=%s", project_id, main_repo)
    return env


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
