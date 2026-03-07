from __future__ import annotations

import typer

from .._client_base import APIError
from ..client import STClient
from ..lib.checkpoint import get_snapshot_info, remove_snapshot
from ..lib.checkpoint_branches import merge_task_branch
from ..output import output_error, output_success
from .done_git import git_stash_pop, git_stash_push, is_working_tree_clean
from .done_subtask import auto_close_subtasks


def ensure_worktree_clean(snapshot_info: dict[str, str | int | None]) -> None:
    """Fail fast when the claimed worktree still has uncommitted changes."""
    raw_wt = snapshot_info.get("worktree_path")
    worktree_path = str(raw_wt) if raw_wt is not None else None
    if not worktree_path or is_working_tree_clean(worktree_path):
        return

    output_error(
        "Claimed worktree has uncommitted changes.\n"
        f"  Path: {worktree_path}\n"
        f"Commit or stash there before running st done."
    )
    raise typer.Exit(1)


def _get_project_id_from_snapshot(snapshot_info: dict[str, str | int | None]) -> str | None:
    project_id = snapshot_info.get("project_id")
    if isinstance(project_id, str) and project_id:
        return project_id
    return None


def _handle_dirty_main(strict: bool) -> bool:
    if is_working_tree_clean():
        return False
    if strict:
        output_error("Main branch has uncommitted changes. Commit/stash them first or use smart mode.")
        raise typer.Exit(1)
    output_success("Main branch dirty, stashing changes before merge...")
    git_stash_push()
    return True


def _auto_verify_readiness(client: STClient, task_id: str) -> None:
    readiness = client.get(f"/api/tasks/{task_id}/completion-readiness")
    if readiness.get("ready"):
        return

    gates = readiness.get("gates", [])
    gate_details = ", ".join(str(gate.get("code", "unknown")) for gate in gates)
    output_error(f"Task not ready to complete: {gate_details}")
    raise typer.Exit(1)


def _request_review_approval(client: STClient, task_id: str) -> None:
    result = client.post(client._global_url(f"/api/review/{task_id}/approve"))
    if result.get("verdict") != "APPROVED":
        output_error("Review approval failed")
        raise typer.Exit(1)


def _perform_completion(
    client: STClient,
    task_id: str,
    snapshot_info: dict[str, str | int | None],
    project_id: str | None,
    strict: bool,
) -> None:
    if not strict:
        _auto_verify_readiness(client, task_id)
        auto_close_subtasks(client, task_id, project_id)
        _request_review_approval(client, task_id)

    merge_task_branch(task_id, project_id=project_id)
    client.update_status(task_id, "completed")
    remove_snapshot(task_id, project_id=project_id)
    _trigger_health_check(task_id, project_id)


def _trigger_health_check(task_id: str, project_id: str | None) -> None:
    if not project_id:
        return
    try:
        from .memory_api import agent_hub_request

        agent_hub_request(
            "POST",
            "/api/site-health-check/trigger",
            json={"project_id": project_id, "task_id": task_id},
            tool_name="st done",
        )
    except Exception:
        pass  # Never block completion on health check trigger failure



def _complete_without_snapshot(
    client: STClient,
    task_id: str,
    message: str | None = None,
) -> dict[str, str | bool]:
    """Close a non-code/admin task without merge or checkpoint requirements."""
    try:
        client.close_task(task_id, reason=message)
    except APIError as e:
        output_error(f"Failed to close task: {e.detail}")
        raise typer.Exit(1) from None

    return {
        "task_id": task_id,
        "action": "completed",
        "merged": False,
        "snapshot_removed": False,
        "base_branch": "main",
    }



def _complete_with_admin_close(
    client: STClient,
    task_id: str,
    snapshot_info: dict[str, str | int | None],
    message: str | None = None,
) -> dict[str, str | bool]:
    """Close a claimed task without merge/review and remove its snapshot."""
    project_id = _get_project_id_from_snapshot(snapshot_info)
    try:
        client.close_task(task_id, reason=message)
    except APIError as e:
        output_error(f"Failed to close task: {e.detail}")
        raise typer.Exit(1) from None

    remove_snapshot(task_id, project_id=project_id)
    return {
        "task_id": task_id,
        "action": "completed",
        "merged": False,
        "snapshot_removed": True,
        "base_branch": str(snapshot_info.get("base_branch", "main")),
    }



def complete_task(
    client: STClient,
    task_id: str,
    message: str | None = None,
    strict: bool = False,
    admin: bool = False,
) -> dict[str, str | bool]:
    """Complete a task with branch merge and snapshot cleanup.

    Smart mode (default): auto-verifies steps, auto-closes subtasks, stashes dirty main.
    Strict mode: fails if gates not pre-passed or main dirty.
    """
    snapshot_info = get_snapshot_info(task_id)
    if not snapshot_info:
        if admin:
            return _complete_without_snapshot(client, task_id, message)
        output_error(f"No checkpoint found for {task_id}. Was it claimed?")
        raise typer.Exit(1)

    if admin:
        return _complete_with_admin_close(client, task_id, snapshot_info, message)

    ensure_worktree_clean(snapshot_info)
    project_id = _get_project_id_from_snapshot(snapshot_info)
    base_branch = str(snapshot_info.get("base_branch", "main"))
    stashed = _handle_dirty_main(strict)

    try:
        _perform_completion(client, task_id, snapshot_info, project_id, strict)
    except SystemExit as exc:
        raise typer.Exit(exc.code) from None
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
