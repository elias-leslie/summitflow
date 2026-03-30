"""Repo-source helpers: DB queries, path translation, and managed-repo collection."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from ..logging_config import get_logger

logger = get_logger(__name__)

# Docker path translation env vars
_HOST_HOME_PATH = os.environ.get("HOST_HOME_PATH", "")
_DOCKER_HOME_MOUNT = os.environ.get("BACKUP_HOST_ROOT", "")

FALLBACK_FILE = Path.home() / ".claude" / "config" / "managed-repos.txt"
WORKTREES_BASE_DIR = Path.home() / ".summitflow" / "worktrees"

# SQL queries
_SQL_SELECT_ROOT_PATHS = "SELECT root_path FROM projects WHERE root_path IS NOT NULL"
_SQL_SELECT_PROJECT_ROOTS = "SELECT id, root_path FROM projects WHERE root_path IS NOT NULL"
_SQL_SELECT_EXTRA_REPOS = (
    "SELECT id, path FROM backup_sources "
    "WHERE path IS NOT NULL AND source_type IN ('config', 'workspace')"
)


def is_valid_git_repo(path: Path) -> bool:
    """Return True if path exists and has a .git directory."""
    return path.exists() and (path / ".git").exists()


def _translate_path(raw: str) -> Path:
    """Translate host path to Docker mount path if running in Docker."""
    if _HOST_HOME_PATH and _DOCKER_HOME_MOUNT and raw.startswith(_HOST_HOME_PATH):
        return Path(_DOCKER_HOME_MOUNT + raw[len(_HOST_HOME_PATH):])
    return Path(raw)


def _normalize_repo_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _load_repo_paths_from_file(path: Path) -> list[Path]:
    """Return valid git repo paths from a newline-delimited config file."""
    if not path.exists():
        return []

    repos: list[Path] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line).expanduser()
        if is_valid_git_repo(candidate):
            repos.append(candidate)
    return repos


def _query_db_root_paths() -> list[str]:
    """Return raw root_path values from the projects table, or [] on error."""
    from ..storage.connection import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute(_SQL_SELECT_ROOT_PATHS)
            return [row[0] for row in cur.fetchall()]
    except Exception:
        logger.debug("Failed to query managed repos from database", exc_info=True)
        return []


def _query_db_project_roots() -> list[tuple[str, str]]:
    """Return project ids and raw root_path values from the projects table, or [] on error."""
    from ..storage.connection import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute(_SQL_SELECT_PROJECT_ROOTS)
            return [(str(row[0]), str(row[1])) for row in cur.fetchall()]
    except Exception:
        logger.debug("Failed to query project repo mapping from database", exc_info=True)
        return []


def _query_db_extra_repos() -> list[tuple[str, str]]:
    """Return non-project managed repo ids and paths from backup_sources, or [] on error."""
    from ..storage.connection import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute(_SQL_SELECT_EXTRA_REPOS)
            return [(str(row[0]), str(row[1])) for row in cur.fetchall()]
    except Exception:
        logger.debug("Failed to query config/workspace repos from backup_sources", exc_info=True)
        return []


def _registered_project_roots() -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for db_project_id, raw_root in _query_db_project_roots():
        translated = _translate_path(raw_root)
        if not is_valid_git_repo(translated):
            continue
        roots[db_project_id] = _normalize_repo_path(translated)
    return roots


def _is_shadowed_project_repo(path: Path, project_roots: dict[str, Path]) -> bool:
    registered_root = project_roots.get(path.name)
    if registered_root is None:
        return False
    return _normalize_repo_path(path) != registered_root


def _collect_db_repos() -> list[Path]:
    """Return valid git repo paths from the database."""
    repos: list[Path] = []
    for raw in _query_db_root_paths():
        path = _translate_path(raw)
        if is_valid_git_repo(path):
            repos.append(path)
    return repos


def _collect_db_extra_repos() -> list[Path]:
    """Return valid config/workspace repo paths from backup_sources."""
    repos: list[Path] = []
    for _, raw in _query_db_extra_repos():
        path = _translate_path(raw)
        if is_valid_git_repo(path):
            repos.append(path)
    return repos


def _resolve_project_id_from_sources(
    repo_path: Path,
    project_roots: list[tuple[str, str]],
    *,
    project_id: str | None = None,
    translate_path: Callable[[str], Path] = _translate_path,
) -> str | None:
    """Resolve a project id from raw project roots while allowing caller-local collaborators."""
    if project_id:
        return project_id

    candidate = _normalize_repo_path(repo_path)
    for db_project_id, raw_root in project_roots:
        if candidate == _normalize_repo_path(translate_path(raw_root)):
            return db_project_id
    return None


def _merge_managed_repos(
    db_repos: list[Path],
    extra_repos: list[Path],
    project_roots: dict[str, Path],
    config_repos: list[Path],
    *,
    validate_repo: Callable[[Path], bool] = is_valid_git_repo,
    is_shadowed_project_repo: Callable[[Path, dict[str, Path]], bool] = _is_shadowed_project_repo,
) -> list[Path]:
    """Merge repo sources without duplicating project-shadowed or invalid config repos."""
    repos = list(db_repos)
    for extra_repo in extra_repos:
        if is_shadowed_project_repo(extra_repo, project_roots):
            continue
        if extra_repo not in repos:
            repos.append(extra_repo)
    for config_repo in config_repos:
        if is_shadowed_project_repo(config_repo, project_roots):
            continue
        if validate_repo(config_repo) and config_repo not in repos:
            repos.append(config_repo)
    return repos


def _resolve_project_id(repo_path: Path, project_id: str | None = None) -> str | None:
    """Resolve the project id for a repo path when it is a registered project root.

    Only repositories from the projects table should receive a project_id.
    Config/workspace/backup repos are managed, but they are not project repos
    and should remain unscoped so the UI can treat them separately.
    """
    return _resolve_project_id_from_sources(
        repo_path,
        _query_db_project_roots(),
        project_id=project_id,
        translate_path=_translate_path,
    )


def get_managed_repos() -> list[Path]:
    """Get list of managed repos from DB-backed sources plus local fallback repos."""
    return _merge_managed_repos(
        _collect_db_repos(),
        _collect_db_extra_repos(),
        _registered_project_roots(),
        _load_repo_paths_from_file(FALLBACK_FILE),
        validate_repo=is_valid_git_repo,
        is_shadowed_project_repo=_is_shadowed_project_repo,
    )
