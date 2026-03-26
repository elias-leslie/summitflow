from __future__ import annotations

import json
import subprocess

import typer

from app.tasks.autonomous.exec_modules.diff_gate import check_diff_gate
from app.utils.shared_paths import resolve_script

from .._client_base import APIError
from ..client import STClient
from ..lib.autosnapshot import capture_lifecycle_baseline
from ..lib.checkpoint import get_snapshot_info, remove_snapshot
from ..lib.checkpoint_branches import merge_task_branch
from ..lib.checkpoint_metadata import SnapshotMeta, save_snapshot_meta
from ..output import output_error, output_success, output_warning
from .done_git import git_stash_pop, git_stash_push, is_working_tree_clean
from .done_subtask import auto_close_subtasks
from .tasks_progress import sync_completed_subtasks


def _get_worktree_path(snapshot_info: dict[str, str | int | None]) -> str | None:
    """Return the worktree path as str, or None if absent/empty."""
    raw = snapshot_info.get("worktree_path")
    return str(raw) if raw else None


def ensure_worktree_clean(snapshot_info: dict[str, str | int | None]) -> None:
    """Fail fast when the claimed worktree still has uncommitted changes."""
    worktree_path = _get_worktree_path(snapshot_info)
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
    readiness = client.get_task_completion_readiness(task_id)
    if readiness.get("ready"):
        return

    gates = readiness.get("gates", [])
    gate_details = ", ".join(
        str(gate.get("gate") or gate.get("code") or "unknown")
        for gate in gates
    )
    output_error(f"Task not ready to complete: {gate_details}")
    raise typer.Exit(1)


def _run_smart_prereqs(client: STClient, task_id: str, project_id: str | None) -> None:
    """Auto-sync subtasks, auto-close open ones, then verify readiness (smart mode only)."""
    subtasks_resp = client.get_subtasks(task_id)
    sync_analysis = sync_completed_subtasks(
        client,
        task_id,
        subtasks_resp.get("subtasks", []),
        acknowledge_none=True,
    )
    if sync_analysis.synced:
        output_success(f"Pre-synced subtasks before completion: {', '.join(sync_analysis.synced)}")
    auto_close_subtasks(client, task_id, project_id)
    _auto_verify_readiness(client, task_id)


def _completion_status_kwargs(client: STClient, task_id: str) -> dict[str, bool]:
    """Return the completion update kwargs needed for the current task state.

    Claimed tasks can still be left in ``pending`` when completion runs.
    In that case, complete them through the existing skip_gates path, which
    also disables transition validation for the final status update.
    """
    try:
        task = client.get_task(task_id)
    except APIError:
        return {}
    if task.get("status") == "pending":
        return {"skip_gates": True}
    return {}


def _perform_completion(
    client: STClient,
    task_id: str,
    snapshot_info: dict[str, str | int | None],
    project_id: str | None,
    strict: bool,
    skip_diff_gate: bool = False,
) -> None:
    # Diff gate: check for meaningful changes before merge
    if not skip_diff_gate:
        worktree_path = _get_worktree_path(snapshot_info)
        if worktree_path:
            diff_result = check_diff_gate(worktree_path)
            if not diff_result.passed:
                output_error(
                    f"Diff gate blocked completion: {diff_result.summary}\n"
                    "  Use --skip-diff-gate for non-code tasks (docs, config)."
                )
                raise typer.Exit(1)

    if not strict:
        _run_smart_prereqs(client, task_id, project_id)

    merge_task_branch(task_id, project_id=project_id)
    try:
        client.update_status(task_id, "completed", **_completion_status_kwargs(client, task_id))
    except APIError as e:
        output_warning(
            f"Code merged but status update failed: {e.detail}\n"
            f"  Recovery: st done {task_id} --admin"
        )
    lifecycle_snapshot = capture_lifecycle_baseline(
        project_id=project_id,
        cwd=snapshot_info.get("worktree_path"),
    )
    if lifecycle_snapshot:
        output_success(f"Protective snapshot captured before cleanup: {lifecycle_snapshot.id}")
    remove_snapshot(task_id, project_id=project_id)
    _trigger_health_check(task_id, project_id)


def _trigger_health_check(task_id: str, project_id: str | None) -> None:
    if not project_id:
        return
    try:
        from ._api_paths import SITE_HEALTH_CHECK_TRIGGER_PATH
        from .memory_api import agent_hub_request

        agent_hub_request(
            "POST",
            SITE_HEALTH_CHECK_TRIGGER_PATH,
            json={"project_id": project_id, "task_id": task_id},
            tool_name="st done",
        )
    except Exception:
        pass  # Never block completion on health check trigger failure


def _publish_completed_work(task_id: str, project_id: str | None) -> None:
    """Publish merged main-branch work so completed tasks do not leave repos ahead/dirty."""
    if not project_id:
        return

    try:
        from app.storage.projects import get_project_root_path
    except Exception:
        return

    project_root = get_project_root_path(project_id)
    if not project_root:
        output_warning(f"Task merged but publish skipped: unknown project root for {project_id}")
        return

    command = [
        str(resolve_script("commit.sh")),
        "--current",
        "--push",
        "--task",
        task_id,
        "--json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        output_warning(f"Task merged but publish failed to start: {exc}")
        return

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        detail = stderr or stdout[:200] or "unknown commit.sh output"
        output_warning(f"Task merged but publish status was unreadable: {detail}")
        return

    repo_result = payload.get("repos", [{}])[0] if payload.get("repos") else {}
    status = str(repo_result.get("status", payload.get("status", "UNKNOWN")))
    reason = str(repo_result.get("reason", "") or "")

    if result.returncode == 0 and status in {"SUCCESS", "SKIP"}:
        return

    detail = reason or stderr or stdout[:200] or "unknown publish failure"
    output_warning(f"Task merged but publish did not complete cleanly: {status} ({detail})")


def _complete_without_snapshot(
    client: STClient,
    task_id: str,
    message: str | None = None,
) -> dict[str, str | bool]:
    """Close a non-code/admin task without merge or checkpoint requirements."""
    try:
        client.close_task(task_id, reason=message, skip_gates=True)
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


def _complete_if_already_completed(
    client: STClient,
    task_id: str,
) -> dict[str, str | bool] | None:
    """Treat completed tasks as idempotent even if checkpoint metadata is gone."""
    try:
        task = client.get_task(task_id)
    except APIError:
        return None

    if task.get("status") != "completed":
        return None

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
        client.close_task(task_id, reason=message, skip_gates=True)
    except APIError as e:
        output_error(f"Failed to close task: {e.detail}")
        raise typer.Exit(1) from None

    lifecycle_snapshot = capture_lifecycle_baseline(
        project_id=project_id,
        cwd=snapshot_info.get("worktree_path"),
    )
    if lifecycle_snapshot:
        output_success(f"Protective snapshot captured before cleanup: {lifecycle_snapshot.id}")
    remove_snapshot(task_id, project_id=project_id)
    return {
        "task_id": task_id,
        "action": "completed",
        "merged": False,
        "snapshot_removed": True,
        "base_branch": str(snapshot_info.get("base_branch", "main")),
    }


def _reconstruct_snapshot_info(
    client: STClient,
    task_id: str,
) -> dict[str, str | int | None] | None:
    """Attempt to reconstruct checkpoint metadata from task API and worktree.

    When the .meta.json file is missing but the task is claimed and a worktree
    still exists, rebuild the metadata so ``st done`` can proceed.
    """
    from ..lib.worktree import get_worktree_info

    try:
        task = client.get_task(task_id)
    except APIError:
        return None

    project_id = task.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        return None

    # Only recover for tasks that are actually in progress.
    if task.get("status") not in ("in_progress", "claimed"):
        return None

    wt_info = get_worktree_info(task_id, project_id)
    if not wt_info:
        return None

    # Rebuild and persist the metadata so future commands work too.
    meta = SnapshotMeta(
        task_id=task_id,
        project_id=project_id,
        base_branch=wt_info.base_branch or "main",
        created_at=task.get("created_at", ""),
        claimed_by=task.get("claimed_by", "unknown"),
        worktree_path=str(wt_info.path),
    )
    save_snapshot_meta(meta)
    output_warning(
        f"Checkpoint metadata was missing for {task_id} — reconstructed from worktree."
    )

    return get_snapshot_info(task_id)


def complete_task(
    client: STClient,
    task_id: str,
    message: str | None = None,
    strict: bool = False,
    admin: bool = False,
    skip_diff_gate: bool = False,
) -> dict[str, str | bool]:
    """Complete a task with branch merge and snapshot cleanup.

    Smart mode (default): auto-verifies steps, auto-closes subtasks, stashes dirty main.
    Strict mode: fails if gates not pre-passed or main dirty.
    """
    snapshot_info = get_snapshot_info(task_id)
    if not snapshot_info:
        if admin:
            return _complete_without_snapshot(client, task_id, message)
        already_completed = _complete_if_already_completed(client, task_id)
        if already_completed:
            return already_completed
        # Try to reconstruct from task/worktree metadata before giving up.
        snapshot_info = _reconstruct_snapshot_info(client, task_id)
    if not snapshot_info:
        output_error(f"No checkpoint found for {task_id}. Was it claimed?")
        raise typer.Exit(1)

    if admin:
        return _complete_with_admin_close(client, task_id, snapshot_info, message)

    ensure_worktree_clean(snapshot_info)
    project_id = _get_project_id_from_snapshot(snapshot_info)
    base_branch = str(snapshot_info.get("base_branch", "main"))
    stashed = _handle_dirty_main(strict)

    try:
        _perform_completion(client, task_id, snapshot_info, project_id, strict, skip_diff_gate)
    except SystemExit as exc:
        raise typer.Exit(exc.code) from None
    finally:
        if stashed:
            git_stash_pop()

    _publish_completed_work(task_id, project_id)

    return {
        "task_id": task_id,
        "action": "completed",
        "merged": True,
        "snapshot_removed": True,
        "base_branch": base_branch,
    }
