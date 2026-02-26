"""Database helpers for git operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def get_project_path(project_id: str) -> Path:
    """Get project root path, raising HTTPException if not found."""
    from ...storage.projects import get_project_root_path

    path = get_project_root_path(project_id)
    if not path:
        raise HTTPException(status_code=404, detail=f"Project root not found: {project_id}")
    return Path(path)


def query_conflicts(project_id: str | None = None) -> list[dict[str, Any]]:
    """Query tasks with active merge conflicts from the database.

    Returns a list of dicts with task_id, title, project_id, and conflict_info.
    """
    from ...storage.connection import get_connection

    sql = """SELECT id, title, project_id, conflict_info
             FROM tasks
             WHERE status = 'conflicted' AND conflict_info IS NOT NULL"""
    params: list[object] = []
    if project_id:
        sql += " AND project_id = %s"
        params.append(project_id)
    sql += " ORDER BY completed_at DESC NULLS LAST"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params) if params else None)
        rows = cur.fetchall()

    return [
        {"task_id": r[0], "title": r[1], "project_id": r[2], "conflict_info": r[3]}
        for r in rows
    ]


def query_recent_merges(
    limit: int = 20, project_id: str | None = None
) -> list[dict[str, Any]]:
    """Query recently merged tasks from the database.

    Returns a list of dicts with task_id, title, project_id, completed_at, pre_sha, merge_sha.
    """
    from ...storage.connection import get_connection

    sql = """SELECT id, title, project_id, completed_at, pre_merge_sha, merge_sha
             FROM tasks
             WHERE status = 'completed'
               AND merge_sha IS NOT NULL
               AND pre_merge_sha IS NOT NULL"""
    params: list[object] = []
    if project_id:
        sql += " AND project_id = %s"
        params.append(project_id)
    sql += " ORDER BY completed_at DESC NULLS LAST LIMIT %s"
    params.append(limit)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    return [
        {
            "task_id": r[0],
            "title": r[1],
            "project_id": r[2],
            "completed_at": r[3],
            "pre_sha": r[4],
            "merge_sha": r[5],
        }
        for r in rows
    ]
