"""Task scope helpers for `st done` closeout."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from .._client_base import APIError
from ..client import STClient

PATH_TOKEN_RE = re.compile(r"(?P<path>(?:[A-Za-z0-9_.@-]+/)+[A-Za-z0-9_.@-]+)")


def git_dirty_paths(repo_root: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", repo_root, "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=False,
    )
    paths: list[str] = []
    for line in result.stdout.splitlines():
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.rsplit(" -> ", 1)[-1].strip()
        if raw_path:
            paths.append(raw_path)
    return sorted(set(paths))


def task_scope_paths(task: dict[str, Any]) -> set[str]:
    scope: set[str] = set()

    def add_value(value: Any) -> None:
        if isinstance(value, str):
            scope.update(match.group("path") for match in PATH_TOKEN_RE.finditer(value))
        elif isinstance(value, list | tuple | set):
            for item in value:
                add_value(item)
        elif isinstance(value, dict):
            for item in value.values():
                add_value(item)

    add_value(task.get("title"))
    add_value(task.get("description"))
    add_value(task.get("done_when"))
    add_value(task.get("context"))
    return scope


def task_with_export_context(client: STClient, task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    """Return task data enriched with export/workflow context when available."""
    try:
        exported = client.export_task_data(task_id)
    except APIError:
        return task
    exported_task = exported.get("task") if isinstance(exported, dict) else None
    if not isinstance(exported_task, dict):
        return task
    merged = dict(task)
    for key in ("description", "done_when", "context"):
        if exported_task.get(key):
            merged[key] = exported_task[key]
    spirit = exported.get("spirit")
    if isinstance(spirit, dict):
        if spirit.get("done_when"):
            merged["done_when"] = spirit["done_when"]
        if spirit.get("context"):
            merged["context"] = spirit["context"]
    return merged
