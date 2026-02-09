"""Database helpers for git operations."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException


def get_project_root(project_id: str) -> Path:
    """Get the root path for a project from the database.

    Args:
        project_id: The project ID to look up

    Returns:
        Path: The project's root path

    Raises:
        HTTPException: If project not found or has no root_path
    """
    from ...storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        project_root = row[0]

    if not project_root:
        raise HTTPException(status_code=400, detail="Project has no root_path configured")

    return Path(project_root)


def get_project_root_with_fallback(project_id: str) -> Path:
    """Get project root from DB or CONFIG_REPOS fallback.

    Args:
        project_id: The project ID to look up

    Returns:
        Path: The project's root path

    Raises:
        HTTPException: If project not found in DB or config
    """
    from ...storage.connection import get_connection
    from ...utils.git_helpers import CONFIG_REPOS

    project_root = None
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if row:
            project_root = row[0]

    # Check config repos if not in DB
    if not project_root:
        for config_repo in CONFIG_REPOS:
            if config_repo.name == project_id:
                project_root = str(config_repo)
                break

    if not project_root:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return Path(project_root)
