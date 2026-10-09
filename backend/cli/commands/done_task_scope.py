"""Task scope helpers for `st done` closeout."""

from __future__ import annotations

import subprocess
from typing import Any

from app.services.task_plan_context import hydrate_task_plan_fields

from .._client_base import APIError
from ..client import STClient


def git_dirty_paths(repo_root: str, *, paths: tuple[str, ...] = ()) -> list[str]:
    """Read literal paths, including both sides of renames, without quote guessing."""
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", repo_root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
         *(["--", *paths] if paths else [])],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Cannot inspect task checkout")
    entries = iter(result.stdout.split("\0"))
    paths: set[str] = set()
    for entry in entries:
        if not entry:
            continue
        paths.add(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            original = next(entries, "")
            if original:
                paths.add(original)
    return sorted(paths)


def task_scope_paths(task: dict[str, Any]) -> set[str]:
    """Only structured ownership declarations establish automatic commit scope."""
    scope: set[str] = set()
    context = task.get("context") or {}
    for value in (task.get("files_to_modify"), context.get("files_to_modify"),
                  task.get("files_to_create"), context.get("files_to_create")):
        if isinstance(value, list | tuple | set):
            scope.update(path for path in value if isinstance(path, str) and path.strip())
    return scope


def closeout_paths(repo_root: str, task_id: str, task: dict[str, Any], *,
                   project_id: str | None, paths: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Resolve declared or leased paths; never infer ownership from prose or HEAD."""
    from pathlib import Path

    from cli.lib.leases import identify_agent, list_active

    root = Path(repo_root).resolve()
    scope = set(paths) if paths else task_scope_paths(task)
    dirty = git_dirty_paths(repo_root)
    if project_id:
        agent_id = identify_agent()[0]
        leases = list_active(project_id)
        if not paths:
            scope.update(path for path in dirty if any(
                lease.agent_id == agent_id and lease.task_id == task_id
                and lease.matches(str(root / path)) for lease in leases
            ))
    else:
        leases = []
    normalized: set[str] = set()
    for value in scope:
        # Git pathspec magic and globs can silently expand a declaration beyond
        # its owner. A caller can select an ordinary directory explicitly.
        if value.startswith(":") or any(char in value for char in "*?["):
            raise ValueError(f"Select literal task paths with --paths; unsupported scope: {value}")
        path = Path(value).expanduser()
        lexical = path if path.is_absolute() else root / path
        try:
            relative = lexical.relative_to(root).as_posix()
            lexical.parent.resolve().relative_to(root)
        except ValueError:
            raise ValueError(f"Task path is outside the checkout: {value}") from None
        if ".." in lexical.parts or (relative in {"", "."} and not paths):
            raise ValueError(f"Select concrete task paths with --paths; ambiguous scope: {value}")
        normalized.add(relative)
    for path in dirty:
        selected = any(prefix == "." or path == prefix or path.startswith(prefix.rstrip("/") + "/")
                       for prefix in normalized)
        if selected and any(lease.matches(str(root / path)) and
                            (lease.agent_id != agent_id or lease.task_id not in {None, task_id})
                            for lease in leases):
            raise ValueError(f"Task path {path} has another active owner; resolve its lease before completion")
    if dirty and not normalized:
        raise ValueError(f"Task scope is ambiguous. Rerun st done {task_id} --paths <owned-path> (repeat for each task path)")
    return tuple(sorted(normalized))


def task_with_export_context(client: STClient, task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    """Return task data enriched with export/workflow context when available."""
    try:
        exported = client.export_task_data(task_id)
    except APIError:
        return hydrate_task_plan_fields(task)
    exported_task = exported.get("task") if isinstance(exported, dict) else None
    if not isinstance(exported_task, dict):
        return hydrate_task_plan_fields(task)
    merged = dict(task)
    for key in ("description", "done_when", "context", "files_to_modify", "files_to_create", "completion_requirements"):
        if exported_task.get(key):
            merged[key] = exported_task[key]
    spirit = exported.get("spirit")
    if isinstance(spirit, dict):
        if spirit.get("done_when"):
            merged["done_when"] = spirit["done_when"]
        merged["context"] = spirit.get("context") or {}
        for field in ("completion_requirements", "files_to_modify", "files_to_create"):
            merged.pop(field, None)
    return hydrate_task_plan_fields(merged)
