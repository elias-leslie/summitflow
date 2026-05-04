"""Missing-checkpoint residue closeout helpers for `st done`."""

from __future__ import annotations

from typing import Any

import typer

from ..client import STClient


def finalize_missing_snapshot_residue(
    client: STClient,
    task_id: str,
    task: dict[str, Any],
    *,
    message: str | None,
    strict: bool,
    skip_diff_gate: bool,
    deps: dict[str, Any],
) -> dict[str, str | bool] | None:
    """Use residue finalize path when checkpoint metadata is gone for a closed task."""
    if strict:
        return None

    status = str(task.get("status") or "")
    if status in {"running", "pending"}:
        return _finalize_active_missing_snapshot(
            client,
            task_id,
            task,
            message=message,
            skip_diff_gate=skip_diff_gate,
            status=status,
            deps=deps,
        )
    if status not in {"completed", "failed"}:
        return None
    return _finalize_terminal_missing_snapshot(task_id, task, status, deps)


def _finalize_active_missing_snapshot(
    client: STClient,
    task_id: str,
    task: dict[str, Any],
    *,
    message: str | None,
    skip_diff_gate: bool,
    status: str,
    deps: dict[str, Any],
) -> dict[str, str | bool]:
    project_id = deps["task_project_id"](task)
    repo_root = deps["checkpoint_repo_root"](project_id)
    scoped_task = deps["task_with_export_context"](client, task_id, task)
    if repo_root and not deps["is_working_tree_clean"](repo_root) and not deps[
        "task_has_published_commit_event"
    ](task_id):
        deps["commit_active_task_work"](repo_root, task_id, message)
    if repo_root:
        result = _close_active_missing_snapshot_if_ready(
            client,
            task_id,
            task,
            scoped_task,
            project_id,
            repo_root,
            skip_diff_gate=skip_diff_gate,
            deps=deps,
        )
        if result is not None:
            return result
    deps["output_error"](
        f"Checkpoint metadata missing for active task {task_id} (status={status}).\n"
        "  No clean checkout or task-linked commit found for safe default closeout."
    )
    raise typer.Exit(1)


def _close_active_missing_snapshot_if_ready(
    client: STClient,
    task_id: str,
    task: dict[str, Any],
    scoped_task: dict[str, Any],
    project_id: str | None,
    repo_root: str,
    *,
    skip_diff_gate: bool,
    deps: dict[str, Any],
) -> dict[str, str | bool] | None:
    base_branch = deps["task_base_branch"](task)
    repo_is_clean = deps["is_working_tree_clean"](repo_root)
    if not repo_is_clean and (
        task_dirty := deps["dirty_paths_in_task_scope"](repo_root, scoped_task)
    ):
        _block_dirty_task_scope(task_dirty, deps)
    if not repo_is_clean and not deps["task_has_published_commit_event"](task_id):
        return None
    if repo_is_clean and not skip_diff_gate and deps["task_has_published_commit_event"](task_id):
        deps["run_diff_gate"](repo_root, task_id, project_id, base_branch)
    return deps["close_missing_checkpoint_active_task"](
        client,
        task_id,
        task,
        project_id=project_id,
        base_branch=base_branch,
        repo_is_clean=repo_is_clean,
    )


def _block_dirty_task_scope(task_dirty: list[str], deps: dict[str, Any]) -> None:
    shown = ", ".join(task_dirty[:8])
    if len(task_dirty) > 8:
        shown += f", +{len(task_dirty) - 8} more"
    deps["output_error"](
        "Task closeout blocked: task-scope dirty paths remain.\n"
        f"  Paths: {shown}\n"
        "  Commit or finish these paths, then rerun st done."
    )
    raise typer.Exit(1)


def _finalize_terminal_missing_snapshot(
    task_id: str,
    task: dict[str, Any],
    status: str,
    deps: dict[str, Any],
) -> dict[str, str | bool]:
    project_id = deps["task_project_id"](task)
    base_branch = deps["task_base_branch"](task)
    deps["output_success"](f"No checkpoint residue for {task_id}; task already {status}.")
    if status == "completed":
        deps["publish_completed_work"](task_id, project_id)
    return deps["done_result"](
        task_id,
        merged=False,
        snapshot_removed=True,
        base_branch=base_branch,
        project_id=project_id,
    )
