"""Helper functions and core logic for the abandon command."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import typer

from app.storage.projects import get_project_root_path

from ..client import APIError, STClient
from ..lib.autosnapshot import capture_lifecycle_baseline
from ..lib.checkpoint import (
    delete_subtask_branch,
    delete_task_branches,
    get_remote_task_branches,
    get_snapshot_info,
    remove_snapshot,
)
from ..lib.checkpoint_branches import get_task_branches
from ..lib.confirm_token import confirm_gate
from ..output import output_error
from .done_validators import is_subtask_id  # noqa: F401  # re-exported for abandon.py


def count_unmerged_commits(task_id: str, project_id: str | None = None) -> int:
    """Count commits on legacy task refs that are not in main/master."""
    repo_root = get_project_root_path(project_id) if project_id else None
    legacy_branches = _legacy_local_branches(task_id, project_id)
    total = 0
    for branch_name in legacy_branches:
        total += _count_branch_commits_ahead(branch_name, repo_root)
    return total


def _count_branch_commits_ahead(branch_name: str, cwd: str | None = None) -> int:
    for base in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "rev-list", "--count", f"{base}..{branch_name}"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            continue
    return 0


def _legacy_local_branches(task_id: str, project_id: str | None = None) -> list[str]:
    """Get all local legacy task-family refs for a task."""
    return [
        str(branch["branch"])
        for branch in get_task_branches(task_id, project_id=project_id)
        if branch.get("branch")
    ]


def check_branch_exists(branch_name: str) -> bool:
    """Return True if git branch exists, False otherwise."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def get_dirty_files(cwd: str | None = None) -> list[str]:
    """Return tracked uncommitted modified/added/deleted files in the working tree."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--no-renames", "--untracked-files=no"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return [entry[3:] for entry in result.stdout.split("\0") if entry and entry[0:2].strip()]
    except (subprocess.CalledProcessError, OSError):
        return []


def _declared_prefixes(task: Mapping[str, Any]) -> set[str]:
    from .done_task_scope import task_scope_paths

    prefixes: set[str] = set()
    for value in task_scope_paths(dict(task)):
        normalized = value.strip().removeprefix("./").rstrip("/")
        # A whole-checkout or pathspec-magic declaration cannot scope a destructive restore.
        if normalized and normalized != "." and not normalized.startswith(":") and ".." not in normalized.split("/"):
            prefixes.add(normalized)
    return prefixes


def split_owned_dirty_files(
    task_id: str,
    task: Mapping[str, Any],
    dirty_files: Sequence[str],
    *,
    project_id: str | None,
    repo_root: str | None,
) -> tuple[list[str], list[str]]:
    """Split dirty files into (owned by this task, everything else).

    A path is owned when the task declares it (files_to_modify/files_to_create)
    or a live lease tagged with this task covers it, and no other task's or
    agent's live lease covers it. Everything else in the shared checkout stays.
    """
    if not dirty_files:
        return [], []
    from ..lib.leases import identify_agent, list_active

    root = Path(repo_root or ".").resolve()
    declared = _declared_prefixes(task)
    leases = list_active(project_id) if project_id else []
    agent_id = identify_agent()[0] if leases else ""
    owned: list[str] = []
    unowned: list[str] = []
    for path in dirty_files:
        absolute = str(root / path)
        matching = [lease for lease in leases if lease.matches(absolute)]
        foreign = any(
            lease.task_id not in {None, task_id} or (lease.task_id is None and lease.agent_id != agent_id)
            for lease in matching
        )
        claimed = any(path == prefix or path.startswith(prefix + "/") for prefix in declared) or any(
            lease.task_id == task_id for lease in matching
        )
        (owned if claimed and not foreign else unowned).append(path)
    return owned, unowned


def discard_dirty_files(cwd: str | None, paths: Sequence[str]) -> None:
    """Discard tracked changes for the task's owned paths only, after abandon confirmation."""
    if not paths:
        return
    result = subprocess.run(
        ["git", "restore", "--staged", "--worktree", "--", *(f":(literal){path}" for path in paths)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return
    detail = result.stderr.strip() or result.stdout.strip() or "git restore failed"
    output_error(f"Failed to discard tracked file changes: {detail}")
    raise typer.Exit(1)


def _build_preview_lines(
    task_id: str,
    legacy_local_branches: list[str],
    remote_branches: list[str],
    has_snapshot: bool,
    snapshot_info: Mapping[str, object] | None,
    unmerged: int,
    dirty_files: list[str],
    kept_files: Sequence[str] = (),
) -> list[str]:
    """Build the preview lines showing what abandon will do."""
    lines: list[str] = []
    lines.append(f"ABANDON {task_id} will:")
    lines.append("  Cancel task status")
    if has_snapshot and snapshot_info:
        lines.append("  Remove checkpoint metadata")
    if legacy_local_branches:
        lines.append(f"  Delete {len(legacy_local_branches)} local legacy task ref(s)")
        for branch in legacy_local_branches[:5]:
            lines.append(f"    {branch}")
        if len(legacy_local_branches) > 5:
            lines.append(f"    ... and {len(legacy_local_branches) - 5} more")
    if remote_branches:
        lines.append(f"  Delete {len(remote_branches)} remote legacy task ref(s)")
        for branch in remote_branches[:5]:
            lines.append(f"    origin/{branch}")
        if len(remote_branches) > 5:
            lines.append(f"    ... and {len(remote_branches) - 5} more")
    if unmerged > 0:
        lines.append(f"  DISCARD {unmerged} commit(s) reachable only from legacy task refs")
    if dirty_files:
        lines.append(f"  DISCARD {len(dirty_files)} tracked uncommitted change(s) owned by this task:")
        for path in dirty_files[:10]:
            lines.append(f"    {path}")
        if len(dirty_files) > 10:
            lines.append(f"    ... and {len(dirty_files) - 10} more")
    if kept_files:
        lines.append(f"  KEEP {len(kept_files)} tracked change(s) this task does not own (shared checkout):")
        for path in list(kept_files)[:10]:
            lines.append(f"    {path}")
        if len(kept_files) > 10:
            lines.append(f"    ... and {len(kept_files) - 10} more")
    lines.append("")
    lines.append("NOTE: Task metadata is append-only; abandon does not restore old DB state.")
    return lines


def abandon_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
    reason: str | None = None,
) -> dict[str, object]:
    """Abandon a subtask without requiring a branch."""
    branch_name = f"{task_id}/{subtask_id}"

    try:
        client.update_subtask(task_id, subtask_id, passes=False)
    except APIError as e:
        typer.echo(f"Warning: Could not reset subtask status: {e.detail}", err=True)

    legacy_branch_deleted: str | None = None
    if check_branch_exists(branch_name):
        if not delete_subtask_branch(task_id, subtask_id):
            output_error(f"Failed to delete legacy branch {branch_name}")
            raise typer.Exit(1)
        legacy_branch_deleted = branch_name

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "abandoned",
        "branch_deleted": legacy_branch_deleted,
    }


def abandon_task(
    client: STClient,
    task_id: str,
    confirm: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Abandon a task — two-pass confirmation required.

    First call (confirm=None): shows preview, generates token, exits.
    Second call (confirm=<token>): validates token, executes abandon.
    """
    command_key = f"abandon-{task_id}"

    snapshot_info = get_snapshot_info(task_id)
    has_snapshot = snapshot_info is not None
    raw_pid = snapshot_info.get("project_id") if snapshot_info else None
    project_id: str | None = str(raw_pid) if raw_pid is not None else None
    task: dict[str, Any] = {}
    try:
        fetched = client.get_task(task_id)
        task = fetched if isinstance(fetched, dict) else {}
    except APIError:
        task = {}
    if project_id is None:
        raw_task_pid = task.get("project_id")
        project_id = str(raw_task_pid) if raw_task_pid else None
    repo_root = get_project_root_path(project_id) if project_id else None
    legacy_local_branches = _legacy_local_branches(task_id, project_id)
    unmerged = count_unmerged_commits(task_id, project_id=project_id)
    remote_branches = get_remote_task_branches(task_id, project_id=project_id)
    owned_dirty, kept_dirty = split_owned_dirty_files(
        task_id, task, get_dirty_files(repo_root), project_id=project_id, repo_root=repo_root,
    )

    preview_lines = _build_preview_lines(
        task_id, legacy_local_branches, remote_branches, has_snapshot, snapshot_info,
        unmerged, owned_dirty, kept_dirty,
    )

    confirm_gate(command_key, confirm, preview_lines, f"st abandon {task_id}")

    try:
        client.update_status(task_id, "cancelled")
    except APIError as e:
        output_error(f"Failed to cancel task before cleanup: {e.detail}")
        raise typer.Exit(1) from None

    if has_snapshot:
        capture_lifecycle_baseline(
            project_id=project_id,
            cwd=get_project_root_path(project_id) if project_id else None,
        )
        remove_snapshot(task_id, project_id=project_id)

    discard_dirty_files(repo_root, owned_dirty)

    delete_task_branches(task_id, project_id=project_id)

    legacy_refs_deleted = len(legacy_local_branches) + len(remote_branches)
    return {
        "task_id": task_id,
        "action": "abandoned",
        "db_restored": False,
        "branches_deleted": legacy_refs_deleted,
        "legacy_refs_deleted": legacy_refs_deleted,
        "snapshot_removed": has_snapshot,
        "discarded_paths": owned_dirty,
        "kept_paths": kept_dirty,
    }
