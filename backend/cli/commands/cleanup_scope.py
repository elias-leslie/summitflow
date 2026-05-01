"""Shared cleanup command scope helpers."""

from __future__ import annotations

from pathlib import Path

from ..config import get_config_optional
from ._git_helpers import _get_managed_repos


def get_project_id(all_projects: bool, project_id_override: str | None = None) -> str | None:
    """Get project ID based on --all flag."""
    if all_projects:
        return None
    if project_id_override:
        return project_id_override
    return get_config_optional().project_id or None


def iter_target_repos(all_projects: bool, project_id_override: str | None = None) -> list[Path]:
    """Return managed repositories relevant to the cleanup request."""
    repos = [repo for repo in _get_managed_repos() if not repo.name.startswith(".")]
    if all_projects:
        return repos
    project_id = get_project_id(False, project_id_override)
    if project_id:
        return [repo for repo in repos if repo.name == project_id]
    return repos[:1] if repos else []


def iter_target_project_ids(all_projects: bool, project_id_override: str | None = None) -> list[str]:
    """Return managed project IDs relevant to the cleanup request."""
    return [repo.name for repo in iter_target_repos(all_projects, project_id_override)]
