from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import typer

from app.storage.projects import get_project_root_path
from app.tasks.autonomous.exec_modules.diff_gate import check_diff_gate
from app.utils.git_base import normalize_base_branch
from app.utils.shared_paths import get_repo_root

from .._client_base import APIError
from ..client import STClient
from ..lib.autosnapshot import capture_lifecycle_baseline
from ..lib.checkpoint import get_snapshot_info, remove_snapshot
from ..lib.checkpoint_branches import merge_task_branch, resolve_task_branch
from ..output import output_error, output_success, output_warning
from .done_git import git_stash_pop, git_stash_push, is_working_tree_clean
from .done_lifecycle import (
    _reconstruct_snapshot_info,
    _task_branch_touched_frontend,
    _trigger_health_check,
)
from .done_subtask import auto_close_subtasks
from .tasks_progress import sync_completed_subtasks


def _done_result(
    task_id: str,
    merged: bool = False,
    snapshot_removed: bool = False,
    base_branch: str = "main",
    project_id: str | None = None,
) -> dict[str, str | bool]:
    return {
        "task_id": task_id,
        "action": "completed",
        "merged": merged,
        "snapshot_removed": snapshot_removed,
        "base_branch": base_branch,
        "project_id": project_id or "",
    }


def _checkpoint_repo_root(project_id: str | None) -> str | None:
    if not project_id:
        return None
    return get_project_root_path(project_id)


def _task_project_id(task: dict[str, Any]) -> str | None:
    raw_project_id = task.get("project_id")
    return str(raw_project_id) if isinstance(raw_project_id, str) and raw_project_id else None


def _task_base_branch(task: dict[str, Any]) -> str:
    raw_base_branch = task.get("base_branch")
    branch = str(raw_base_branch) if isinstance(raw_base_branch, str) and raw_base_branch else "main"
    project_id = _task_project_id(task)
    repo_root = _checkpoint_repo_root(project_id)
    return normalize_base_branch(branch, repo_root)


def ensure_checkpoint_clean(
    snapshot_info: dict[str, str | int | None],
) -> None:
    """Fail fast when the claimed checkpoint branch still has uncommitted changes."""
    raw_project_id = snapshot_info.get("project_id")
    project_id = str(raw_project_id) if isinstance(raw_project_id, str) and raw_project_id else None
    repo_root = _checkpoint_repo_root(project_id)
    if not repo_root or is_working_tree_clean(repo_root):
        return
    output_error(
        "Claimed checkpoint branch has uncommitted changes.\n"
        f"  Path: {repo_root}\n"
        f"Commit or stash there before running st done."
    )
    raise typer.Exit(1)


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
        str(gate.get("gate") or gate.get("code") or "unknown") for gate in gates
    )
    output_error(f"Task not ready to complete: {gate_details}")
    raise typer.Exit(1)


def _run_smart_prereqs(
    client: STClient,
    task_id: str,
    project_id: str | None,
    *,
    merge_subtask_branches: bool = True,
) -> None:
    subtasks_resp = client.get_subtasks(task_id)
    sync_analysis = sync_completed_subtasks(
        client, task_id, subtasks_resp.get("subtasks", []), acknowledge_none=True,
    )
    if sync_analysis.synced:
        output_success(f"Pre-synced subtasks before completion: {', '.join(sync_analysis.synced)}")
    auto_close_subtasks(client, task_id, project_id, merge_branches=merge_subtask_branches)
    _auto_verify_readiness(client, task_id)


def _completion_skip_gates(client: STClient, task_id: str) -> bool:
    try:
        task = client.get_task(task_id)
    except APIError:
        return False
    return task.get("status") in {"pending", "failed"}


def _task_has_published_commit_event(task_id: str) -> bool:
    """Return True when st commit recorded a pushed task commit."""
    try:
        from app.storage.events import get_events_by_trace
    except Exception:
        return False
    commit_event_re = re.compile(r"\bst commit\b.*\bcommit=[0-9a-f]+\b.*\bpushed=true\b")
    try:
        events = get_events_by_trace(task_id, limit=50)
    except Exception:
        return False
    return any(
        message and commit_event_re.search(message)
        for event in reversed(events)
        if (message := event.get("message"))
    )


def _run_diff_gate(repo_root: str, task_id: str, project_id: str | None, base_branch: str) -> None:
    diff_result = check_diff_gate(
        repo_root,
        head_ref=resolve_task_branch(task_id, project_id=project_id),
        base_ref=base_branch,
    )
    if diff_result.passed:
        return
    output_error(
        f"Diff gate blocked completion: {diff_result.summary}\n"
        "  Use --skip-diff-gate for non-code tasks (docs, config)."
    )
    raise typer.Exit(1)


def _close_task_safely(client: STClient, task_id: str, message: str | None) -> None:
    try:
        client.close_task(task_id, reason=message, skip_gates=True)
    except APIError as e:
        output_error(f"Failed to close task: {e.detail}")
        raise typer.Exit(1) from None


def _capture_and_remove_snapshot(
    task_id: str, project_id: str | None
) -> None:
    repo_root = _checkpoint_repo_root(project_id)
    lifecycle_snapshot = capture_lifecycle_baseline(project_id=project_id, cwd=repo_root)
    if lifecycle_snapshot:
        output_success(f"Protective snapshot captured before cleanup: {lifecycle_snapshot.id}")
    remove_snapshot(task_id, project_id=project_id)


def _warn_on_publish_failure(result: subprocess.CompletedProcess[str]) -> None:
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        detail = stderr or stdout[:200] or "unknown st commit output"
        output_warning(f"Task merged but publish status was unreadable: {detail}")
        return
    repo_result = payload.get("repos", [{}])[0] if payload.get("repos") else {}
    status = str(repo_result.get("status", payload.get("status", "UNKNOWN")))
    reason = str(repo_result.get("reason", "") or "")
    detail_text = str(repo_result.get("detail", "") or "")
    if result.returncode == 0 and status in {"SUCCESS", "SKIP"}:
        return
    detail = detail_text or reason or stderr or stdout[:200] or "unknown publish failure"
    output_warning(f"Task merged but publish did not complete cleanly: {status} ({detail})")


def _cleanup_completed_bookmark(st_path: str, project_root: str, task_id: str) -> None:
    if not (Path(project_root) / ".jj").is_dir():
        return
    command = [
        st_path,
        "jj",
        "push",
        "--delete-bookmark",
        "--task",
        task_id,
        "--repo",
        project_root,
    ]
    try:
        result = subprocess.run(
            command, cwd=project_root, capture_output=True, text=True, check=False, timeout=300
        )
    except (subprocess.SubprocessError, OSError) as exc:
        output_warning(f"Task merged but bookmark cleanup failed to start: {exc}")
        return
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown bookmark cleanup failure"
        output_warning(f"Task merged but bookmark cleanup failed: {detail[:200]}")


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
    st_path = shutil.which("st") or str(get_repo_root() / "backend" / ".venv" / "bin" / "st")
    command = [st_path, "--no-compact", "commit", "--push", "--task", task_id, "--message", f"complete {task_id}"]
    try:
        result = subprocess.run(
            command, cwd=project_root, capture_output=True, text=True, check=False, timeout=600
        )
    except (subprocess.SubprocessError, OSError) as exc:
        output_warning(f"Task merged but publish failed to start: {exc}")
        return
    _warn_on_publish_failure(result)
    if result.returncode == 0:
        _cleanup_completed_bookmark(st_path, project_root, task_id)


def _perform_completion(
    client: STClient,
    task_id: str,
    snapshot_info: dict[str, str | int | None],
    project_id: str | None,
    strict: bool,
    skip_diff_gate: bool = False,
) -> None:
    repo_root = _checkpoint_repo_root(
        str(snapshot_info.get("project_id")) if snapshot_info.get("project_id") else None
    )
    base_branch = normalize_base_branch(str(snapshot_info.get("base_branch") or "main"), repo_root)
    snapshot_info["base_branch"] = base_branch
    frontend_changed = _task_branch_touched_frontend(task_id, project_id, base_branch=base_branch)
    if repo_root and not skip_diff_gate:
        _run_diff_gate(repo_root, task_id, project_id, base_branch)
    if not strict:
        _run_smart_prereqs(client, task_id, project_id)
    merge_task_branch(task_id, project_id=project_id)
    try:
        client.update_status(task_id, "completed", skip_gates=_completion_skip_gates(client, task_id))
    except APIError as e:
        output_warning(
            f"Code merged but status update failed: {e.detail}\n"
            f"  Recovery: st done {task_id} --admin"
        )
    _capture_and_remove_snapshot(task_id, project_id)
    if frontend_changed:
        _trigger_health_check(task_id, project_id)


def _finalize_missing_snapshot_residue(
    client: STClient,
    task_id: str,
    task: dict[str, Any],
    *,
    strict: bool,
) -> dict[str, str | bool] | None:
    """Use residue finalize path when checkpoint metadata is gone for a closed task."""
    if strict:
        return None

    status = str(task.get("status") or "")
    if status in {"running", "pending"}:
        project_id = _task_project_id(task)
        repo_root = _checkpoint_repo_root(project_id)
        if repo_root and is_working_tree_clean(repo_root) and _task_has_published_commit_event(task_id):
            _run_smart_prereqs(client, task_id, project_id, merge_subtask_branches=False)
            try:
                client.update_status(task_id, "completed", skip_gates=_completion_skip_gates(client, task_id))
            except APIError as e:
                output_error(f"Failed to close task after published commit: {e.detail}")
                raise typer.Exit(1) from None
            output_success(f"No checkpoint for {task_id}; closed from pushed st commit event.")
            return _done_result(
                task_id,
                merged=False,
                snapshot_removed=True,
                base_branch=_task_base_branch(task),
                project_id=project_id,
            )
        output_error(
            f"Checkpoint metadata missing for active task {task_id} (status={status}).\n"
            "  Restore/claim the task checkpoint first; residue finalize is only for closed tasks."
        )
        raise typer.Exit(1)
    if status not in {"completed", "failed"}:
        return None

    project_id = _task_project_id(task)
    base_branch = _task_base_branch(task)
    output_success(f"No checkpoint residue for {task_id}; task already {status}.")
    if status == "completed":
        _publish_completed_work(task_id, project_id)
    return _done_result(
        task_id,
        merged=False,
        snapshot_removed=True,
        base_branch=base_branch,
        project_id=project_id,
    )


def _load_snapshot_info(
    client: STClient,
    task_id: str,
    admin: bool,
    message: str | None,
) -> tuple[dict[str, str | int | None] | None, dict[str, str | bool] | None]:
    """Resolve snapshot info, handling missing-snapshot cases early.

    Returns (snapshot_info, early_result). If early_result is set, the caller
    should return it immediately. If both are None, no checkpoint was found.
    """
    snapshot_info = get_snapshot_info(task_id)
    if snapshot_info:
        return snapshot_info, None
    if admin:
        _close_task_safely(client, task_id, message)
        return None, _done_result(task_id)
    return _reconstruct_snapshot_info(client, task_id), None


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
    snapshot_info, early = _load_snapshot_info(client, task_id, admin, message)
    if early is not None:
        return early
    if not snapshot_info:
        task: dict[str, Any] | None = None
        try:
            task = client.get_task(task_id)
        except APIError:
            task = None
        if task is not None:
            recovered = _finalize_missing_snapshot_residue(
                client,
                task_id,
                task,
                strict=strict,
            )
            if recovered is not None:
                return recovered
        output_error(f"No checkpoint found for {task_id}. Was it claimed?")
        raise typer.Exit(1)

    if admin:
        pid = snapshot_info.get("project_id")
        project_id = str(pid) if isinstance(pid, str) and pid else None
        _close_task_safely(client, task_id, message)
        _capture_and_remove_snapshot(task_id, project_id)
        return _done_result(
            task_id,
            snapshot_removed=True,
            base_branch=str(snapshot_info.get("base_branch", "main")),
            project_id=project_id,
        )

    ensure_checkpoint_clean(snapshot_info)
    pid = snapshot_info.get("project_id")
    project_id = str(pid) if isinstance(pid, str) and pid else None
    base_branch = normalize_base_branch(
        str(snapshot_info.get("base_branch", "main")),
        _checkpoint_repo_root(project_id),
    )
    stashed = _handle_dirty_main(strict)

    try:
        _perform_completion(client, task_id, snapshot_info, project_id, strict, skip_diff_gate)
        _publish_completed_work(task_id, project_id)
    except SystemExit as exc:
        raise typer.Exit(exc.code if isinstance(exc.code, int) else 1) from None
    finally:
        if stashed:
            git_stash_pop()
    return _done_result(
        task_id,
        merged=True,
        snapshot_removed=True,
        base_branch=base_branch,
        project_id=project_id,
    )
