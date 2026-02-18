"""Task completion logic for done command.

Handles task completion with branch merge and snapshot cleanup.
"""

from __future__ import annotations

import subprocess
from typing import Any

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import (
    get_snapshot_info,
    merge_task_branch,
    remove_snapshot,
)
from ..output import output_error, output_warning
from .done_git import git_stash_pop, git_stash_push, is_working_tree_clean
from .done_memory import report_task_outcome
from .done_subtask import auto_close_subtasks
from .done_validators import parse_db_error


def _auto_commit_worktree(worktree_path: str) -> bool:
    """Auto-commit tracked changes in worktree via commit.sh.

    Uses --skip-checks (st done runs its own verify_commands) and
    --no-push (branch is ephemeral — about to be merged and deleted).
    commit.sh handles pre-commit hook retries automatically.
    """
    try:
        result = subprocess.run(
            ["commit.sh", "--skip-checks", "--no-push", "--current"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        output_warning(f"Auto-commit failed: {e}")
        return False


def ensure_worktree_clean(snapshot_info: dict[str, str | int | None]) -> None:
    """Ensure worktree is clean, auto-committing tracked changes if needed."""
    raw_wt = snapshot_info.get("worktree_path")
    worktree_path: str | None = str(raw_wt) if raw_wt is not None else None

    if not worktree_path or is_working_tree_clean(worktree_path):
        return

    if _auto_commit_worktree(worktree_path):
        return

    output_error(
        f"Worktree has uncommitted changes that could not be auto-committed.\n"
        f"  Path: {worktree_path}\n"
        f"Commit manually: cd {worktree_path} && git add -u && git commit -m 'message'"
    )
    raise typer.Exit(1)


def _output_gate_error(gate: dict[str, str]) -> None:
    """Output error message for a specific gate."""
    gate_name = gate["gate"]
    if gate_name == "zero_steps":
        output_error(
            "Cannot complete: Task has no steps. Create subtasks with steps first."
        )
        return
    if gate_name == "subtasks":
        output_error(f"Cannot complete: Incomplete subtasks: {gate['detail']}")
        return
    if gate_name == "steps":
        output_error(f"Cannot complete: Unverified steps: {gate['detail']}")


def validate_completion_readiness(client: STClient, task_id: str) -> None:
    """Pre-validate completion gates BEFORE merging (fail fast)."""
    try:
        readiness = client.get(
            client._global_url(f"/tasks/{task_id}/completion-readiness")
        )
        if readiness.get("ready"):
            return

        for gate in readiness.get("gates", []):
            _output_gate_error(gate)
        raise typer.Exit(1)
    except APIError as e:
        output_error(f"Pre-validation failed: {e.detail}")
        raise typer.Exit(1) from None


def merge_and_update_status(
    client: STClient,
    task_id: str,
    project_id: str | None,
) -> None:
    """Merge task branch and update status to completed."""
    try:
        merge_task_branch(task_id, project_id=project_id)
    except SystemExit:
        output_error("Merge failed. Resolve conflicts manually, then retry.")
        raise typer.Exit(1) from None

    try:
        client.update_status(task_id, "completed")
    except APIError as e:
        detail: dict[str, str] = (
            e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
        )
        helpful = parse_db_error(detail)
        if helpful:
            output_error(helpful)
        else:
            output_error(f"Failed to complete task: {e.detail}")
        raise typer.Exit(1) from None


def _handle_dirty_main(strict: bool) -> bool:
    """Handle dirty main branch based on mode. Returns True if stashed."""
    main_dirty = not is_working_tree_clean()
    if not main_dirty:
        return False

    if strict:
        output_error(
            "Main repo has uncommitted changes.\n"
            "Commit or stash first before completing task."
        )
        raise typer.Exit(1)
    return git_stash_push()


def _get_project_id_from_snapshot(snapshot_info: dict[str, str | int | None]) -> str | None:
    """Extract project_id from snapshot info."""
    raw_pid = snapshot_info.get("project_id")
    return str(raw_pid) if raw_pid is not None else None


def _run_ai_review(client: STClient, task_id: str) -> dict[str, Any] | None:
    """Trigger AI review via API. Returns None on failure (non-blocking)."""
    try:
        return client.post(client._global_url(f"/tasks/{task_id}/review"), json={})
    except Exception:
        return None


def _should_run_ai_review(client: STClient, task_id: str) -> bool:
    """Check if AI review should run for this task."""
    try:
        task = client.get(client._global_url(f"/tasks/{task_id}"))
        return bool(task.get("ai_review", True))
    except Exception:
        return True  # Default to running review if we can't fetch the flag


def _perform_completion(
    client: STClient,
    task_id: str,
    snapshot_info: dict[str, str | int | None],
    project_id: str | None,
    strict: bool,
) -> None:
    """Perform the actual task completion steps."""
    if not strict:
        auto_close_subtasks(client, task_id, project_id)

    validate_completion_readiness(client, task_id)

    # AI review gate — skip for tasks with ai_review=False (e.g. refactors)
    if _should_run_ai_review(client, task_id):
        review_result = _run_ai_review(client, task_id)
        if review_result and review_result.get("verdict") not in ("APPROVED", "UNKNOWN"):
            concerns = review_result.get("concerns", [])
            output_error(
                f"AI Review: {review_result.get('verdict')}\n"
                + "\n".join(f"  - {c}" for c in concerns)
            )
            raise typer.Exit(1)

    merge_and_update_status(client, task_id, project_id)

    claimed_at = snapshot_info.get("created_at") if snapshot_info else None
    report_task_outcome(
        task_id,
        succeeded=True,
        project_id=project_id,
        started_at=str(claimed_at) if claimed_at else None,
    )

    remove_snapshot(task_id, project_id=project_id)


def _validate_snapshot(task_id: str) -> dict[str, str | int | None]:
    """Validate snapshot exists and return it."""
    snapshot_info = get_snapshot_info(task_id)
    if not snapshot_info:
        output_error(f"No checkpoint found for {task_id}. Was it claimed?")
        raise typer.Exit(1)
    return snapshot_info


def complete_task(
    client: STClient,
    task_id: str,
    message: str | None = None,
    strict: bool = False,
) -> dict[str, str | bool]:
    """Complete a task with branch merge and snapshot cleanup.

    Smart mode (default): auto-verifies steps, auto-closes subtasks, stashes dirty main.
    Strict mode: fails if gates not pre-passed or main dirty.
    """
    snapshot_info = _validate_snapshot(task_id)
    ensure_worktree_clean(snapshot_info)
    project_id = _get_project_id_from_snapshot(snapshot_info)
    base_branch = str(snapshot_info.get("base_branch", "main"))
    stashed = _handle_dirty_main(strict)

    try:
        _perform_completion(client, task_id, snapshot_info, project_id, strict)
    finally:
        if stashed:
            git_stash_pop()

    return {
        "task_id": task_id,
        "action": "completed",
        "merged": True,
        "snapshot_removed": True,
        "base_branch": base_branch,
    }
