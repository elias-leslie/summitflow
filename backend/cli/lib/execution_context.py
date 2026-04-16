"""Shared execution-context helpers for CLI commands.

Keeps project/worktree detection logic in one place for CLI consumers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


def _resolve_git_path(args: list[str], cwd: Path | None = None) -> Path | None:
    """Resolve a git-derived absolute path for the current checkout."""
    target = cwd or Path.cwd()
    try:
        result = subprocess.run(
            args,
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def _read_project_id_from_index(root: Path) -> str | None:
    """Read a project id from a repo-local .index.yaml when present."""
    index_path = root / ".index.yaml"
    if not index_path.exists():
        return None
    try:
        data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    project_id = data.get("project")
    if isinstance(project_id, str):
        project_id = project_id.strip()
        if project_id:
            return project_id
    return None


def resolve_git_common_dir(cwd: Path | None = None) -> Path | None:
    """Return the common git dir for the current checkout, if available."""
    return _resolve_git_path(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)


def resolve_checkout_root(cwd: Path | None = None) -> Path | None:
    """Return the root directory for the current checkout/worktree."""
    return _resolve_git_path(["git", "rev-parse", "--path-format=absolute", "--show-toplevel"], cwd)


def canonical_repo_root(cwd: Path | None = None) -> Path | None:
    """Resolve the canonical repo root backing the current checkout."""
    common_dir = resolve_git_common_dir(cwd)
    if common_dir is None:
        return None
    if common_dir.name == ".git":
        return common_dir.parent.resolve()
    return common_dir.resolve()


def resolve_checkout_project_id(cwd: Path | None = None) -> str | None:
    """Resolve the project id associated with the current checkout, ignoring CLI overrides."""
    target = (cwd or Path.cwd()).resolve()
    candidates: list[Path] = []
    seen: set[Path] = set()

    for candidate in (resolve_checkout_root(target), canonical_repo_root(target), target, *target.parents):
        if candidate is None:
            continue
        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen:
            continue
        candidates.append(resolved_candidate)
        seen.add(resolved_candidate)

    for candidate in candidates:
        project_id = _read_project_id_from_index(candidate)
        if project_id:
            return project_id
    return None
