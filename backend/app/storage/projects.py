"""Project storage - Database operations for projects.

Centralizes project-related database queries.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..project_identity import canonicalize_project_name
from ..utils.env_files import project_env_files, scrub_env_keys_from_files
from .connection import get_cursor

logger = get_logger(__name__)


def project_exists(project_id: str) -> bool:
    """Return True if project exists, False otherwise."""
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        return cur.fetchone() is not None


def get_project_root_path(project_id: str) -> str | None:
    """Return project root path or None if project not found."""
    with get_cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        return row[0] if row else None


def find_project_by_cwd(cwd: str) -> dict[str, Any] | None:
    """Find project whose root_path matches the given working directory.

    Resolves cwd and project roots as filesystem paths, then returns the most
    specific root that contains the cwd.
    """
    try:
        candidate = Path(cwd).expanduser().resolve()
    except OSError:
        candidate = Path(cwd).expanduser()

    matches: list[tuple[int, dict[str, Any]]] = []
    for project in list_projects():
        root_path = project.get("root_path")
        if not root_path:
            continue
        try:
            root = Path(root_path).expanduser().resolve()
        except OSError:
            root = Path(root_path).expanduser()

        if candidate == root or root in candidate.parents:
            matches.append((len(str(root)), project))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    project = matches[0][1]
    return {
        "id": project["id"],
        "name": canonicalize_project_name(
            project["id"],
            project["name"],
            project["root_path"],
        ),
        "root_path": project["root_path"],
    }


def _apply_working_dir_pythonpath(env: dict[str, str], working_dir: str) -> None:
    """Inject worktree backend dir into PYTHONPATH if it exists."""
    backend_path = Path(working_dir) / "backend"
    if not backend_path.is_dir():
        return
    backend_dir = str(backend_path)
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
    since worktrees don't have their own .venv). Keys declared in the
    project's env files are stripped first so stale shell exports cannot
    override the repo's canonical .env/.env.local/.env.example sources.

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

    env_paths = project_env_files(Path(main_repo))
    if working_dir:
        working_root = Path(working_dir)
        if working_root != Path(main_repo):
            env_paths.extend(project_env_files(working_root))
    env = scrub_env_keys_from_files(env, env_paths)

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
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, name, root_path, created_at FROM projects ORDER BY created_at"
        )
        return [
            {
                "id": row[0],
                "name": canonicalize_project_name(row[0], row[1], row[2]),
                "root_path": row[2],
                "created_at": row[3],
            }
            for row in cur.fetchall()
        ]
