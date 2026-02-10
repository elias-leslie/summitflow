"""Done command for st CLI.

Checkpoint-aware completion for tasks and subtasks.
Merges git branches and cleans up DB snapshots.

Smart default: auto-verifies steps, auto-closes subtasks, stash-merge-pop.
Use --strict for old gate-check-only behavior.
"""

from __future__ import annotations

import subprocess
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import (
    get_snapshot_info,
    merge_subtask_branch,
    merge_task_branch,
    remove_snapshot,
)
from ..output import output_error, output_success, output_warning

app = typer.Typer(help="Complete task or subtask work")


def _is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    if len(parts) != 2:
        return False
    return parts[0].isdigit() and parts[1].isdigit()


def _is_working_tree_clean(path: str | None = None) -> bool:
    """Check if git working tree is clean.

    Args:
        path: Directory to check. If None, checks current directory.

    Returns:
        True if clean (no uncommitted changes), or if path doesn't exist.
        False if there are uncommitted changes.
    """
    from pathlib import Path

    # If path specified but doesn't exist, consider it "clean" (nothing to commit)
    if path and not Path(path).exists():
        return True

    cmd = ["git", "status", "--porcelain"]
    if path:
        cmd = ["git", "-C", path, "status", "--porcelain"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return len(result.stdout.strip()) == 0
    except subprocess.CalledProcessError:
        return False


def _git_stash_push() -> bool:
    """Stash uncommitted changes on main for merge.

    Returns:
        True if a stash entry was created, False if nothing to stash.
    """
    try:
        # Count stash entries before
        before = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
        before_count = len(before.stdout.strip().splitlines()) if before.stdout.strip() else 0

        subprocess.run(
            ["git", "stash", "push", "-m", "st-done-auto"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Count stash entries after to detect if stash was created
        after = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
        after_count = len(after.stdout.strip().splitlines()) if after.stdout.strip() else 0

        return after_count > before_count
    except subprocess.CalledProcessError as e:
        output_warning(f"git stash push failed: {e.stderr}")
        return False


def _git_stash_pop() -> None:
    """Pop the most recent stash entry."""
    try:
        subprocess.run(
            ["git", "stash", "pop"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        output_warning(f"git stash pop failed (manual resolve may be needed): {e.stderr}")


def _parse_db_error(detail: Any) -> str | None:
    """Parse DB trigger error messages into helpful guidance."""
    if not isinstance(detail, (str, dict)):
        return None

    msg = str(detail).lower() if isinstance(detail, str) else str(detail.get("detail", "")).lower()

    if "zero steps" in msg or ("steps" in msg and "zero" in msg):
        return "Cannot complete: Task has no steps. Create subtasks with steps first."

    if "steps" in msg and ("incomplete" in msg or "not verified" in msg):
        return "Cannot complete: Some steps not verified. Run: st step pass <subtask> <step>"

    if "dependencies" in msg or "depends on" in msg:
        return "Cannot complete: Blocking dependencies incomplete. Complete them first."

    if "qa" in msg and ("pending" in msg or "signoff" in msg):
        return "Cannot complete: QA status pending. Run: st qa pass <task-id>"

    if "subtask" in msg and ("incomplete" in msg or "not all" in msg):
        return "Cannot complete task: Some subtasks incomplete. Run: st subtask list <task-id>"

    return None


def _auto_close_subtasks(
    client: STClient,
    task_id: str,
    project_id: str | None,
) -> None:
    """Auto-verify steps, acknowledge citations, and close unpassed subtasks.

    For each subtask not yet passed:
    1. Verify unpassed steps via API (server-side verify_command execution)
    2. Acknowledge citations if not already done
    3. Close the subtask and merge its branch

    Aborts immediately if any step verification fails.
    """
    subtasks_resp = client.get_subtasks(task_id, include_steps=True)
    subtasks = subtasks_resp.get("subtasks", [])

    for subtask in subtasks:
        subtask_id = subtask.get("subtask_id") or subtask.get("id")
        if not subtask_id:
            continue

        # Skip already-passed subtasks
        if subtask.get("passes") is True:
            continue

        # Get steps for this subtask
        steps = subtask.get("steps") or client.get_steps(task_id, subtask_id)

        # Verify unpassed steps
        for step in steps:
            step_number = step.get("step_number")
            if step_number is None:
                continue

            # Skip already-passed steps
            if step.get("passes") is True:
                continue

            # Skip plan_defect steps (they have fix steps)
            if step.get("status") == "plan_defect":
                continue

            # Verify via API (triggers server-side verify_command)
            try:
                result = client.update_step(task_id, subtask_id, step_number, passes=True)
                if result.get("passes") is False:
                    output_error(
                        f"Step {subtask_id}#{step_number} verification failed. Aborting."
                    )
                    raise typer.Exit(1)
            except APIError as e:
                output_error(
                    f"Step {subtask_id}#{step_number} failed: {e.detail}"
                )
                raise typer.Exit(1) from None

        # Acknowledge citations if not already done
        citations_status = subtask.get("citations_status") or subtask.get("citations_acknowledged")
        if not citations_status:
            try:
                client.acknowledge_no_citations(task_id, subtask_id)
            except APIError:
                pass  # Non-fatal — citations may already be acknowledged

        # Close subtask via API
        try:
            client.update_subtask(task_id, subtask_id, passes=True)
        except APIError as e:
            detail: dict[str, Any] = (
                e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
            )
            helpful = _parse_db_error(detail)
            if helpful:
                output_error(helpful)
            else:
                output_error(f"Failed to close subtask {subtask_id}: {e.detail}")
            raise typer.Exit(1) from None

        # Merge subtask branch
        try:
            merge_subtask_branch(task_id, subtask_id, project_id=project_id)
        except SystemExit:
            output_error(f"Subtask {subtask_id} merge failed. Resolve conflicts manually.")
            raise typer.Exit(1) from None


def _complete_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
    message: str | None = None,
) -> dict[str, Any]:
    """Complete a subtask with git branch merge.

    DB triggers verify all steps passed.
    """
    # Check working tree is clean
    if not _is_working_tree_clean():
        output_error("Working tree has uncommitted changes.\nCommit first: git commit -m 'message'")
        raise typer.Exit(1)

    # Get project_id from snapshot for per-project worktree paths
    snapshot_info = get_snapshot_info(task_id)
    raw_pid = snapshot_info.get("project_id") if snapshot_info else None
    project_id: str | None = str(raw_pid) if raw_pid is not None else None

    # Mark subtask as passed via API (DB triggers verify steps)
    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        # Parse DB trigger errors
        detail: dict[str, Any] = (
            e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
        )
        helpful = _parse_db_error(detail)
        if helpful:
            output_error(helpful)
        else:
            output_error(f"Failed to complete subtask: {e.detail}")
        raise typer.Exit(1) from None

    # Merge subtask branch to task branch
    try:
        merge_subtask_branch(task_id, subtask_id, project_id=project_id)
    except SystemExit:
        # merge_subtask_branch already prints error
        output_error("Merge failed. Resolve conflicts manually, then retry.")
        raise typer.Exit(1) from None

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "completed",
        "merged": True,
    }


def _report_task_outcome(task_id: str, *, succeeded: bool) -> None:
    """Report task outcome to Agent Hub memory system (fire-and-forget).

    Credits loaded memories when tasks succeed, enabling utility_score tracking.
    Non-blocking — failures are logged but never block task completion.
    """
    try:
        from .memory_api import agent_hub_request

        agent_hub_request(
            "POST",
            "/api/memory/task-outcome",
            json={"task_id": task_id, "succeeded": succeeded},
            tool_name="st done",
        )
    except Exception:
        pass  # Fire-and-forget — never block task completion


def _complete_task(
    client: STClient,
    task_id: str,
    message: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Complete a task with branch merge and snapshot cleanup.

    Default (smart): auto-verifies unpassed steps, auto-closes subtasks,
    stashes dirty main for merge then pops.

    With strict=True: old behavior — fails if any gate not already passed,
    fails if main is dirty.
    """
    # Check for existing checkpoint FIRST (need worktree path for clean check)
    snapshot_info = get_snapshot_info(task_id)
    if not snapshot_info:
        output_error(f"No checkpoint found for {task_id}. Was it claimed?")
        raise typer.Exit(1)

    # Check working tree is clean - check WORKTREE, not main repo
    raw_wt = snapshot_info.get("worktree_path")
    worktree_path: str | None = str(raw_wt) if raw_wt is not None else None
    if worktree_path and not _is_working_tree_clean(worktree_path):
        output_error(
            f"Worktree has uncommitted changes.\n"
            f"  Path: {worktree_path}\n"
            f"Commit first: cd {worktree_path} && git commit -m 'message'"
        )
        raise typer.Exit(1)

    # Get project_id from snapshot for per-project worktree paths
    raw_pid = snapshot_info.get("project_id")
    project_id: str | None = str(raw_pid) if raw_pid is not None else None

    # Handle dirty main: stash (smart) or error (strict)
    main_dirty = not _is_working_tree_clean()
    stashed = False
    if main_dirty:
        if strict:
            output_error(
                "Main repo has uncommitted changes.\nCommit or stash first before completing task."
            )
            raise typer.Exit(1)
        stashed = _git_stash_push()

    try:
        # Smart mode: auto-verify and auto-close unpassed subtasks
        if not strict:
            _auto_close_subtasks(client, task_id, project_id)

        # Pre-validate completion gates BEFORE merging (fail fast, avoid half-done state)
        try:
            readiness = client.get(client._global_url(f"/tasks/{task_id}/completion-readiness"))
            if not readiness.get("ready"):
                for g in readiness.get("gates", []):
                    gate_name = g["gate"]
                    if gate_name == "zero_steps":
                        output_error(
                            "Cannot complete: Task has no steps. Create subtasks with steps first."
                        )
                    elif gate_name == "subtasks":
                        output_error(f"Cannot complete: Incomplete subtasks: {g['detail']}")
                    elif gate_name == "steps":
                        output_error(f"Cannot complete: Unverified steps: {g['detail']}")
                raise typer.Exit(1)
        except APIError as e:
            output_error(f"Pre-validation failed: {e.detail}")
            raise typer.Exit(1) from None

        # Merge task branch — only reached if completion gates will pass
        try:
            merge_task_branch(task_id, project_id=project_id)
        except SystemExit:
            output_error("Merge failed. Resolve conflicts manually, then retry.")
            raise typer.Exit(1) from None

        # Mark task as completed via API (gates verify all subtasks passed)
        # Runs AFTER merge so if gates fail, code is merged but task stays "running" (recoverable)
        try:
            client.update_status(task_id, "completed")
        except APIError as e:
            detail: dict[str, Any] = (
                e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
            )
            helpful = _parse_db_error(detail)
            if helpful:
                output_error(helpful)
            else:
                output_error(f"Failed to complete task: {e.detail}")
            raise typer.Exit(1) from None

        # Report task outcome to Agent Hub memory system (fire-and-forget)
        _report_task_outcome(task_id, succeeded=True)

        # Remove snapshot after successful merge + status update
        remove_snapshot(task_id, project_id=project_id)

    finally:
        # Always pop stash if we stashed, even on failure
        if stashed:
            _git_stash_pop()

    return {
        "task_id": task_id,
        "action": "completed",
        "merged": True,
        "snapshot_removed": True,
    }


@app.command(name="done")
def done_command(
    id: Annotated[str, typer.Argument(help="Task ID or subtask ID (e.g., 1.1)")],
    task_id: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Parent task ID (for subtask completion)"),
    ] = None,
    message: Annotated[
        str | None,
        typer.Option("--message", "-m", help="Completion message"),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Strict mode: fail on unpassed gates (old behavior)"),
    ] = False,
) -> None:
    """Complete a task or subtask.

    For subtasks: Verifies all steps passed (via DB trigger), merges branch.
    For tasks: Auto-verifies steps, closes subtasks, merges branches, removes checkpoint.

    Smart default: auto-closes unpassed gates, stashes dirty main for merge.
    Use --strict for old behavior that errors on unpassed gates.

    Examples:
        st done task-abc123           # Smart: auto-verify + merge + cleanup
        st done task-abc123 --strict  # Old: fail if gates not pre-passed
        st done 1.1 -t task-abc123   # Complete subtask 1.1 (unchanged)
    """
    from ..context import require_task_id

    client = STClient()

    # Determine if this is a task or subtask
    if _is_subtask_id(id):
        # Subtask completion - need task_id
        resolved_task_id = require_task_id(task_id)
        _complete_subtask(client, id, resolved_task_id, message)
        output_success(f"Subtask {id} completed. Branch merged.")
    else:
        _complete_task(client, id, message, strict=strict)
        output_success(f"Task {id} completed. Checkpoint removed.")
        typer.echo(f"  Merged to: {get_snapshot_info(id) or 'main'}")
