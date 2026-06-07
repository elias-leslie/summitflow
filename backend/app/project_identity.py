"""Repo-local project identity manifest loader."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.utils.shared_paths import get_repo_root

_WORKSPACES_ROOT = Path(os.environ.get("ST_WORKSPACES_ROOT", Path.home() / ".local" / "share" / "summitflow" / "workspaces"))
_PROJECTS_ROOT = _WORKSPACES_ROOT / "projects"
_MANIFEST_NAME = "project.identity.json"


@lru_cache(maxsize=256)
def _read_manifest(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


@lru_cache(maxsize=1)
def _workspace_manifest_paths() -> tuple[str, ...]:
    paths: list[str] = []
    if not _PROJECTS_ROOT.is_dir():
        return _local_manifest_paths()
    paths = [
        str(path)
        for path in sorted(_PROJECTS_ROOT.glob(f"*/{_MANIFEST_NAME}"))
        if path.is_file()
    ]
    paths.extend(_local_manifest_paths())
    return tuple(dict.fromkeys(paths))


@lru_cache(maxsize=1)
def _local_manifest_paths() -> tuple[str, ...]:
    repo_root = get_repo_root().resolve()
    candidates = [repo_root / _MANIFEST_NAME]
    if repo_root.parent.is_dir():
        candidates.extend(sorted(repo_root.parent.glob(f"*/{_MANIFEST_NAME}")))
    return tuple(
        dict.fromkeys(str(path) for path in candidates if path.is_file())
    )


def _project_aliases(project: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("id", "repo_name"):
        value = project.get(key)
        if isinstance(value, str) and value:
            aliases.add(value)
    for key in ("legacy_ids", "repo_aliases"):
        values = project.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value:
                    aliases.add(value)
    return aliases


def _ordered_project_aliases(project: dict[str, Any]) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for key in ("id", "repo_name"):
        value = project.get(key)
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            aliases.append(value)
    for key in ("legacy_ids", "repo_aliases"):
        values = project.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value and value not in seen:
                    seen.add(value)
                    aliases.append(value)
    return tuple(aliases)


def _manifest_matches_project_id(manifest_path: str, project_id: str) -> bool:
    payload = _read_manifest(manifest_path)
    project = payload.get("project")
    return isinstance(project, dict) and project_id in _project_aliases(project)


def get_project_identity_path(
    project_id: str,
    root_path: str | None = None,
) -> Path | None:
    """Return the project identity manifest path if present."""
    if root_path:
        candidate = Path(root_path) / _MANIFEST_NAME
        if candidate.is_file():
            return candidate

    candidate = _PROJECTS_ROOT / project_id / _MANIFEST_NAME
    if candidate.is_file():
        return candidate

    for manifest_path in _workspace_manifest_paths():
        if _manifest_matches_project_id(manifest_path, project_id):
            return Path(manifest_path)

    return None


def get_project_identity(
    project_id: str,
    root_path: str | None = None,
) -> dict[str, Any] | None:
    """Load the project identity manifest when available."""
    manifest_path = get_project_identity_path(project_id, root_path)
    if manifest_path is None:
        return None
    return _read_manifest(str(manifest_path))


def get_project_aliases(
    project_id: str,
    root_path: str | None = None,
) -> tuple[str, ...]:
    """Return canonical id plus any configured legacy aliases."""
    identity = get_project_identity(project_id, root_path)
    if not identity:
        return (project_id,)

    project = identity.get("project")
    if not isinstance(project, dict):
        return (project_id,)

    aliases = _ordered_project_aliases(project)
    return aliases or (project_id,)


def get_project_canonical_id(
    project_id: str,
    root_path: str | None = None,
    fallback: str | None = None,
) -> str | None:
    """Return the canonical manifest project id when available."""
    identity = get_project_identity(project_id, root_path)
    if not identity:
        return fallback

    project = identity.get("project")
    if not isinstance(project, dict):
        return fallback

    canonical_id = project.get("id")
    if isinstance(canonical_id, str) and canonical_id:
        return canonical_id
    return fallback


def get_project_identity_root(
    project_id: str,
    root_path: str | None = None,
) -> str | None:
    """Return the manifest root path for a project when available."""
    manifest_path = get_project_identity_path(project_id, root_path)
    if manifest_path is None:
        return None
    return str(manifest_path.parent.resolve())


def get_project_upload_dir_name(
    project_id: str,
    root_path: str | None = None,
) -> str | None:
    """Return the configured upload directory name for a project when available."""
    identity = get_project_identity(project_id, root_path)
    if not identity:
        return None

    artifacts = identity.get("artifacts")
    if not isinstance(artifacts, dict):
        return None

    upload_dir_name = artifacts.get("upload_dir_name")
    if isinstance(upload_dir_name, str) and upload_dir_name:
        return upload_dir_name
    return None


def get_project_display_name(
    project_id: str,
    root_path: str | None = None,
    fallback: str | None = None,
) -> str | None:
    """Return manifest display name when available, otherwise fallback."""
    identity = get_project_identity(project_id, root_path)
    if not identity:
        return fallback

    project = identity.get("project")
    if not isinstance(project, dict):
        return fallback

    display_name = project.get("display_name")
    if isinstance(display_name, str) and display_name:
        return display_name
    return fallback


def canonicalize_project_name(
    project_id: str,
    name: str,
    root_path: str | None = None,
) -> str:
    """Prefer manifest display name over caller-provided mutable labels."""
    return get_project_display_name(project_id, root_path, name) or name


def list_project_identities() -> list[dict[str, Any]]:
    """Return all workspace project identity payloads."""
    return [_read_manifest(path) for path in _workspace_manifest_paths()]
