"""Helper functions and core logic for the abandon command."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping

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
            ["git", "status", "--porcelain", "--no-renames", "--untracked-files=no"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return [
            line[3:] for line in result.stdout.splitlines()
            if line and line[0:2].strip()
        ]
    except (subprocess.CalledProcessError, OSError):
        return []


def discard_dirty_files(cwd: str | None = None) -> None:
    """Discard tracked working-tree changes after abandon confirmation."""
    result = subprocess.run(
        ["git", "restore", "--staged", "--worktree", "."],
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
        lines.append(f"  DISCARD {len(dirty_files)} tracked uncommitted file change(s):")
        for path in dirty_files[:10]:
            lines.append(f"    {path}")
        if len(dirty_files) > 10:
            lines.append(f"    ... and {len(dirty_files) - 10} more")
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
    if project_id is None:
        try:
            task = client.get_task(task_id)
            raw_task_pid = task.get("project_id") if isinstance(task, dict) else None
            project_id = str(raw_task_pid) if raw_task_pid else None
        except APIError:
            project_id = None
    repo_root = get_project_root_path(project_id) if project_id else None
    legacy_local_branches = _legacy_local_branches(task_id, project_id)
    unmerged = count_unmerged_commits(task_id, project_id=project_id)
    remote_branches = get_remote_task_branches(task_id, project_id=project_id)
    dirty_files = get_dirty_files(repo_root)

    preview_lines = _build_preview_lines(
        task_id, legacy_local_branches, remote_branches, has_snapshot, snapshot_info,
        unmerged, dirty_files,
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

    if dirty_files:
        discard_dirty_files(repo_root)

    delete_task_branches(task_id, project_id=project_id)

    legacy_refs_deleted = len(legacy_local_branches) + len(remote_branches)
    return {
        "task_id": task_id,
        "action": "abandoned",
        "db_restored": False,
        "branches_deleted": legacy_refs_deleted,
        "legacy_refs_deleted": legacy_refs_deleted,
        "snapshot_removed": has_snapshot,
    }
