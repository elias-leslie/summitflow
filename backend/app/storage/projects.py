"""Project storage - Database operations for projects.

Centralizes project-related database queries.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from .connection import get_connection

logger = get_logger(__name__)


def get_project_test_config(project_id: str) -> tuple[Any, ...] | None:
    """Get project test configuration (root_path, test_config) or None."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path, test_config FROM projects WHERE id = %s",
            (project_id,),
        )
        return cur.fetchone()


def project_exists(project_id: str) -> bool:
    """Return True if project exists, False otherwise."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        return cur.fetchone() is not None


def get_project_root_path(project_id: str) -> str | None:
    """Return project root path or None if project not found."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_all_project_root_paths() -> list[str]:
    """Return list of root paths for all registered projects."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE root_path IS NOT NULL")
        return [row[0] for row in cur.fetchall()]


def find_project_by_cwd(cwd: str) -> dict[str, Any] | None:
    """Find project whose root_path matches the given working directory.

    Checks if cwd starts with any project's root_path. Returns the most
    specific (longest) match or None.
    """
    with get_connection() as conn, conn.cursor() as cur:
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
        if not row:
            return None
        return {"id": row[0], "name": row[1], "root_path": row[2]}


def _apply_working_dir_pythonpath(env: dict[str, str], working_dir: str) -> None:
    """Inject worktree backend dir into PYTHONPATH if it exists."""
    backend_dir = str(Path(working_dir) / "backend")
    if not Path(backend_dir).is_dir():
        return
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{backend_dir}:{existing}" if existing else backend_dir


def _resolve_venv(main_repo: str) -> Path | None:
    """Return the first valid venv path found under main_repo, or None."""
    candidates = [
        Path(main_repo) / "backend" / ".venv",
        Path(main_repo) / ".venv",
    ]
    for venv_path in candidates:
        if (venv_path / "bin" / "python").exists():
            return venv_path
    return None


def build_project_env(project_id: str | None, working_dir: str | None = None) -> dict[str, str]:
    """Build environment dict with the correct project venv on PATH.

    Single source of truth for subprocess environment in verification.
    Resolves the main repo's venv from project_id (handles worktrees
    since worktrees don't have their own .venv).

    Args:
        project_id: Project ID for resolving venv paths.
        working_dir: Optional worktree path. When provided, injects it into
                     PYTHONPATH so import checks resolve against the worktree
                     rather than the main repo's editable install.
    """
    env = os.environ.copy()
    if not project_id:
        return env

    main_repo = get_project_root_path(project_id)
    if not main_repo:
        return env

    venv_path = _resolve_venv(main_repo)
    if not venv_path:
        logger.debug("no_venv_found: project_id=%s main_repo=%s", project_id, main_repo)
        return env

    venv_bin = str(venv_path / "bin")
    env["VIRTUAL_ENV"] = str(venv_path)
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    env.pop("PYTHONHOME", None)
    logger.info("resolved_project_venv: venv=%s project_id=%s", venv_path, project_id)

    if working_dir:
        _apply_working_dir_pythonpath(env, working_dir)

    return env


def list_projects() -> list[dict[str, Any]]:
    """Return list of all projects with id, name, root_path, created_at."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, root_path, created_at FROM projects ORDER BY created_at"
        )
        return [
            {"id": row[0], "name": row[1], "root_path": row[2], "created_at": row[3]}
            for row in cur.fetchall()
        ]
