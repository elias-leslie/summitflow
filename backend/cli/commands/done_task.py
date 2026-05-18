from __future__ import annotations

import os
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
from ..lib.checkpoint_branches import resolve_task_branch
from ..lib.commit_workflow import CommitError, commit_repo
from ..output import output_error, output_success, output_warning
from .done_git import git_stash_pop, git_stash_push, is_working_tree_clean
from .done_lifecycle import (
    _reconstruct_snapshot_info,
    _task_branch_touched_frontend,
    _trigger_health_check,
)
from .done_subtask import auto_close_subtasks
from .done_task_publish import (
    cleanup_completed_bookmark,
    publish_completed_work,
    warn_on_publish_failure,
)
from .done_task_residue import finalize_missing_snapshot_residue
from .done_task_scope import git_dirty_paths as _git_dirty_paths
from .done_task_scope import task_scope_paths as _task_scope_paths
from .done_task_scope import task_with_export_context as _task_with_export_context
from .tasks_progress import sync_completed_subtasks


def _done_result(task_id: str, merged: bool = False, snapshot_removed: bool = False, base_branch: str = "main", project_id: str | None = None) -> dict[str, str | bool]:
    return {"task_id": task_id, "action": "completed", "merged": merged, "snapshot_removed": snapshot_removed, "base_branch": base_branch, "project_id": project_id or ""}


def _checkpoint_repo_root(project_id: str | None) -> str | None:
    return get_project_root_path(project_id) if project_id else None


def _task_project_id(task: dict[str, Any]) -> str | None:
    raw = task.get("project_id")
    return str(raw) if isinstance(raw, str) and raw else None


def _task_base_branch(task: dict[str, Any]) -> str:
    raw = task.get("base_branch")
    branch = str(raw) if isinstance(raw, str) and raw else "main"
    return normalize_base_branch(branch, _checkpoint_repo_root(_task_project_id(task)))


def ensure_checkpoint_clean(snapshot_info: dict[str, str | int | None], *, task_id: str | None = None, message: str | None = None, strict: bool = True) -> None:
    raw_pid = snapshot_info.get("project_id")
    project_id = str(raw_pid) if isinstance(raw_pid, str) and raw_pid else None
    repo_root = _checkpoint_repo_root(project_id)
    if not repo_root or is_working_tree_clean(repo_root):
        return
    if not strict and task_id:
        _commit_active_task_work(repo_root, task_id, message)
        if is_working_tree_clean(repo_root):
            return
    output_error(f"Claimed checkpoint branch has uncommitted changes.\n  Path: {repo_root}\n  Smart mode could not create a clean checkpoint. Fix the reported closeout blocker, then rerun st done.")
    raise typer.Exit(1)


def _auto_verify_readiness(client: STClient, task_id: str) -> None:
    readiness = client.get_task_completion_readiness(task_id)
    if readiness.get("ready"):
        return
    gates = readiness.get("gates", [])
    gate_details = ", ".join(str(gate.get("gate") or gate.get("code") or "unknown") for gate in gates)
    output_error(f"Task not ready to complete: {gate_details}")
    raise typer.Exit(1)


def _run_smart_prereqs(client: STClient, task_id: str, project_id: str | None) -> None:
    subtasks_resp = client.get_subtasks(task_id)
    sync_analysis = sync_completed_subtasks(client, task_id, subtasks_resp.get("subtasks", []), acknowledge_none=True)
    if sync_analysis.synced:
        output_success(f"Pre-synced subtasks before completion: {', '.join(sync_analysis.synced)}")
    auto_close_subtasks(client, task_id, project_id)
    _auto_verify_readiness(client, task_id)


def _completion_skip_gates(client: STClient, task_id: str) -> bool:
    try:
        task = client.get_task(task_id)
    except APIError:
        return False
    return task.get("status") in {"pending", "failed"}


def _task_has_published_commit_event(task_id: str) -> bool:
    import re
    try:
        from app.storage.events import get_events_by_trace
    except Exception:
        return False
    commit_event_re = re.compile(r"\bst commit\b.*\bcommit=[0-9a-f]+\b.*\bpushed=true\b")
    try:
        events = get_events_by_trace(task_id, limit=50)
    except Exception:
        return False
    return any(message and commit_event_re.search(message) for event in reversed(events) if (message := event.get("message")))


def _commit_active_task_work(repo_root: str, task_id: str, message: str | None) -> None:
    commit_message = (message or f"complete {task_id}").strip()
    try:
        result = commit_repo(Path(repo_root), message=commit_message, task_id=task_id, push=True)
    except CommitError as exc:
        output_error(f"Task closeout blocked: st commit failed: {exc}")
        raise typer.Exit(1) from None
    if result.get("status") == "BLOCKED":
        detail = str(result.get("detail") or result.get("reason") or "quality gates failed")
        output_error(f"Task closeout blocked: {detail}")
        raise typer.Exit(2)
    if result.get("status") == "SUCCESS":
        try:
            from app.storage.events import log_task_event
            detail_parts = [f"change={result.get('change_id', '')}", f"commit={result.get('commit_id') or result.get('sha') or ''}", f"bookmark={result.get('bookmark', '')}", f"op={result.get('operation_id', '')}", f"pushed={str(result.get('pushed', False)).lower()}"]
            log_task_event(task_id, "st commit " + " ".join(part for part in detail_parts if not part.endswith("=")))
        except Exception:
            pass
    output_success(f"Committed task work before completion: {result.get('commit_id') or result.get('sha')}")


def _close_missing_checkpoint_active_task(client: STClient, task_id: str, task: dict[str, Any], project_id: str | None, *, base_branch: str, repo_is_clean: bool) -> dict[str, str | bool]:
    _run_smart_prereqs(client, task_id, project_id)
    try:
        client.update_status(task_id, "completed", skip_gates=_completion_skip_gates(client, task_id))
    except APIError as e:
        output_error(f"Failed to close task: {e.detail}")
        raise typer.Exit(1) from None
    if repo_is_clean:
        _publish_completed_work(task_id, project_id)
    output_success(f"No checkpoint for {task_id}; closed from clean/task-committed checkout.")
    return _done_result(task_id, merged=False, snapshot_removed=True, base_branch=base_branch, project_id=project_id)


_DOC_OR_CONFIG_SUFFIXES = (".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json")
_DOC_OR_CONFIG_FILENAMES = {"CHANGELOG", "CHANGES", "NOTICE", "AUTHORS", "LICENSE", "README"}


def _is_doc_or_config_path(path: str) -> bool:
    p = path.strip().lower()
    if not p:
        return False
    if "/docs/" in p or p.startswith("docs/"):
        return True
    if any(p.endswith(suffix) for suffix in _DOC_OR_CONFIG_SUFFIXES):
        return True
    basename = p.rsplit("/", 1)[-1].split(".", 1)[0].upper()
    return basename in _DOC_OR_CONFIG_FILENAMES


def _is_diff_docs_or_config_only(repo_root: str, head_ref: str, base_branch: str) -> bool:
    """Return True if every changed file in the task branch is docs/config."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "diff", "--name-only", f"{base_branch}...{head_ref}"],
            capture_output=True, text=True, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return bool(paths) and all(_is_doc_or_config_path(p) for p in paths)


def _run_diff_gate(repo_root: str, task_id: str, project_id: str | None, base_branch: str) -> None:
    # Emergency escape: ST_DIFF_GATE=off disables the gate entirely.
    if (os.environ.get("ST_DIFF_GATE") or "").strip().lower() == "off":
        return
    head_ref = resolve_task_branch(task_id, project_id=project_id)
    # Auto-route: docs/config-only changes skip the code-quality slice.
    if _is_diff_docs_or_config_only(repo_root, head_ref, base_branch):
        output_success("Diff gate auto-skipped: changes are docs/config only.")
        return
    diff_result = check_diff_gate(repo_root, head_ref=head_ref, base_ref=base_branch)
    if diff_result.passed:
        return
    output_error(
        f"Diff gate blocked completion: {diff_result.summary}\n"
        f"Resolution: address the gate findings, or set ST_DIFF_GATE=off for an emergency override."
    )
    raise typer.Exit(1)


def _close_task_safely(client: STClient, task_id: str, message: str | None) -> None:
    _auto_verify_readiness(client, task_id)
    try:
        client.close_task(task_id, reason=message, skip_gates=True)
    except APIError as e:
        output_error(f"Failed to close task: {e.detail}")
        raise typer.Exit(1) from None


def _finalize_completed_task_status(
    client: STClient,
    task_id: str,
    *,
    message: str | None,
) -> bool:
    skip_gates = _completion_skip_gates(client, task_id)
    try:
        client.update_status(task_id, "completed", skip_gates=skip_gates)
        return False
    except APIError as e:
        if not skip_gates:
            try:
                client.close_task(task_id, reason=message, skip_gates=True)
                output_warning(
                    "Status finalize needed forced close after merge cleanup; "
                    "completion gates already passed but transition drifted."
                )
                return True
            except APIError:
                pass
        output_warning(f"Code merged but status update failed: {e.detail}\n  Recovery: st done {task_id} --admin")
        return False


def _capture_and_remove_snapshot(task_id: str, project_id: str | None) -> None:
    repo_root = _checkpoint_repo_root(project_id)
    lifecycle_snapshot = capture_lifecycle_baseline(project_id=project_id, cwd=repo_root)
    if lifecycle_snapshot:
        output_success(f"Protective snapshot captured before cleanup: {lifecycle_snapshot.id}")
    remove_snapshot(task_id, project_id=project_id)


def _publish_completed_work(task_id: str, project_id: str | None) -> None:
    publish_completed_work(
        task_id,
        project_id,
        deps={
            "cleanup_completed_bookmark": lambda st_path, project_root, tid: cleanup_completed_bookmark(st_path, project_root, tid, subprocess_module=subprocess, output_warning=output_warning),
            "get_repo_root": get_repo_root,
            "output_warning": output_warning,
            "shutil": shutil,
            "subprocess": subprocess,
            "warn_on_publish_failure": lambda result: warn_on_publish_failure(result, output_warning),
        },
    )


def complete_task(client: STClient, task_id: str, message: str | None = None, strict: bool = False, admin: bool = False, skip_diff_gate: bool = False) -> dict[str, str | bool]:
    """Complete a task with branch merge and snapshot cleanup.

    Smart mode (default): auto-verifies, checkpoints, publishes, closes, and cleans up.
    Strict mode: fails if gates not pre-passed or main dirty.
    """
    snapshot_info = get_snapshot_info(task_id)
    if snapshot_info:
        if admin:
            return _complete_admin(client, task_id, snapshot_info, message)
        return _complete_with_snapshot(client, task_id, snapshot_info, message=message, strict=strict, skip_diff_gate=skip_diff_gate)
    if admin:
        _close_task_safely(client, task_id, message)
        return _done_result(task_id)
    snapshot_info = _reconstruct_snapshot_info(client, task_id)
    if snapshot_info:
        if admin:
            return _complete_admin(client, task_id, snapshot_info, message)
        return _complete_with_snapshot(client, task_id, snapshot_info, message=message, strict=strict, skip_diff_gate=skip_diff_gate)
    return _complete_without_snapshot(client, task_id, message=message, strict=strict, skip_diff_gate=skip_diff_gate)


def _complete_without_snapshot(client: STClient, task_id: str, *, message: str | None, strict: bool, skip_diff_gate: bool) -> dict[str, str | bool]:
    task: dict[str, Any] | None = None
    try:
        task = client.get_task(task_id)
    except APIError:
        task = None
    if task is not None:
        recovered = finalize_missing_snapshot_residue(
            client, task_id, task, message=message, strict=strict, skip_diff_gate=skip_diff_gate,
            deps={
                "checkpoint_repo_root": _checkpoint_repo_root,
                "close_missing_checkpoint_active_task": _close_missing_checkpoint_active_task,
                "commit_active_task_work": _commit_active_task_work,
                "dirty_paths_in_task_scope": lambda repo_root, t: [
                    path for path in _git_dirty_paths(repo_root)
                    if path in (scope := _task_scope_paths(t)) or any(path.startswith(f"{prefix.rstrip('/')}/") for prefix in scope)
                ],
                "done_result": _done_result,
                "is_working_tree_clean": is_working_tree_clean,
                "output_error": output_error,
                "output_success": output_success,
                "publish_completed_work": _publish_completed_work,
                "run_diff_gate": _run_diff_gate,
                "task_base_branch": _task_base_branch,
                "task_has_published_commit_event": _task_has_published_commit_event,
                "task_project_id": _task_project_id,
                "task_with_export_context": _task_with_export_context,
            },
        )
        if recovered is not None:
            return recovered
    output_error(f"No checkpoint found for {task_id}. Was it claimed?")
    raise typer.Exit(1)


def _complete_admin(client: STClient, task_id: str, snapshot_info: dict[str, str | int | None], message: str | None) -> dict[str, str | bool]:
    pid = snapshot_info.get("project_id")
    project_id = str(pid) if isinstance(pid, str) and pid else None
    _close_task_safely(client, task_id, message)
    _capture_and_remove_snapshot(task_id, project_id)
    return _done_result(task_id, snapshot_removed=True, base_branch=str(snapshot_info.get("base_branch", "main")), project_id=project_id)


def _complete_with_snapshot(client: STClient, task_id: str, snapshot_info: dict[str, str | int | None], *, message: str | None, strict: bool, skip_diff_gate: bool) -> dict[str, str | bool]:
    ensure_checkpoint_clean(snapshot_info, task_id=task_id, message=message, strict=strict)
    pid = snapshot_info.get("project_id")
    project_id = str(pid) if isinstance(pid, str) and pid else None
    repo_root = _checkpoint_repo_root(project_id)
    base_branch = normalize_base_branch(str(snapshot_info.get("base_branch", "main")), repo_root)
    snapshot_info["base_branch"] = base_branch
    stashed = False
    if not is_working_tree_clean():
        if strict:
            output_error("Main branch has uncommitted changes. Commit/stash them first or use smart mode.")
            raise typer.Exit(1)
        output_success("Main branch dirty, stashing changes before merge...")
        git_stash_push()
        stashed = True
    publish_failed = False
    try:
        frontend_changed = _task_branch_touched_frontend(task_id, project_id, base_branch=base_branch)
        if repo_root and not skip_diff_gate:
            _run_diff_gate(repo_root, task_id, project_id, base_branch)
        if not strict:
            _run_smart_prereqs(client, task_id, project_id)
        _finalize_completed_task_status(client, task_id, message=message)
        # Publish FIRST so a failed publish leaves the snapshot intact for safe retry.
        try:
            _publish_completed_work(task_id, project_id)
        except Exception as publish_exc:
            publish_failed = True
            output_warning(
                f"Publish failed mid-done: {publish_exc}\n"
                f"Resolution: checkpoint preserved; rerun `st done {task_id}` to retry publish."
            )
            raise typer.Exit(1) from None
        _capture_and_remove_snapshot(task_id, project_id)
        if frontend_changed:
            _trigger_health_check(task_id, project_id)
    except SystemExit as exc:
        raise typer.Exit(exc.code if isinstance(exc.code, int) else 1) from None
    finally:
        if stashed:
            git_stash_pop()
    return _done_result(
        task_id,
        merged=True,
        snapshot_removed=not publish_failed,
        base_branch=base_branch,
        project_id=project_id,
    )
