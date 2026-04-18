"""Complex endpoint logic for git operations."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.tasks.update import update_task_fields
from ...tasks.autonomous.cleanup.merge_operations import merge_and_cleanup_task_checkpoint
from ...tasks.autonomous.cleanup.merge_types import MergeResult
from ...utils.git_helpers import (
    get_all_branches,
    get_managed_repos,
    get_recent_commits,
    get_task_diff,
    list_snapshots,
    revert_to_snapshot,
)
from ...utils.shared_paths import resolve_script
from ..models.git_models import (
    CommitInfo,
    ConflictInfo,
    DiffStats,
    MergedTaskSummary,
    ProjectDashboardResponse,
    RecentMergesResponse,
    SnapshotInfo,
    TaskDiffResponse,
)
from .checkpoint_helpers import collect_checkpoints, enrich_snapshots
from .db_helpers import (
    get_project_path,
    get_project_root_with_fallback,
    query_conflicts,
    query_recent_merges,
)

_logger = get_logger(__name__)


def _smart_sync_env() -> tuple[Path, dict[str, str] | None]:
    """Return (script_path, env) for the commit.sh smart-sync invocation."""
    host_root = os.environ.get("BACKUP_HOST_ROOT")
    script_path = resolve_script("commit.sh")
    if not host_root:
        return script_path, None

    env = os.environ.copy()
    env["HOME"] = host_root
    host_bin_dirs = [f"{host_root}/.local/bin", f"{host_root}/bin", f"{host_root}/.cargo/bin"]
    env["PATH"] = ":".join(host_bin_dirs) + ":" + env.get("PATH", "")
    ssh_dir = f"{host_root}/.ssh"
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {ssh_dir}/id_ed25519 -o UserKnownHostsFile={ssh_dir}/known_hosts"
    )
    return script_path, env


def _parse_smart_sync_output(output: str, stderr_text: str, returncode: int) -> dict[str, Any]:
    """Parse commit.sh JSON output into a normalized response dict."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return {
            "success": False,
            "status": "UNKNOWN",
            "gates": "",
            "errors": [stderr_text[:200]],
            "message": "",
            "reason": "json_parse_failed",
            "detail": stderr_text[:200],
            "pushed": False,
            "raw_output": output + stderr_text,
        }
    repo_data = data.get("repos", [{}])[0] if data.get("repos") else {}
    detail = str(repo_data.get("detail", "") or stderr_text or "")
    error_text = detail or str(repo_data.get("reason", "") or "")
    return {
        "success": returncode == 0,
        "status": repo_data.get("status", data.get("status", "UNKNOWN")),
        "gates": repo_data.get("gates", ""),
        "errors": [error_text] if error_text else [],
        "message": repo_data.get("message", ""),
        "reason": repo_data.get("reason", ""),
        "detail": detail,
        "pushed": repo_data.get("pushed", False),
        "workflow_summary": repo_data.get("workflow_summary", ""),
        "workflow_hint": repo_data.get("workflow_hint", ""),
        "workflow_runs": repo_data.get("workflow_runs", []),
        "raw_output": output + stderr_text,
    }


async def execute_smart_sync(project_root: Path) -> dict[str, Any]:
    """Execute smart sync operation using commit.sh script."""
    import asyncio
    from asyncio import subprocess as aio_subprocess

    script_path, env = _smart_sync_env()
    try:
        proc = await asyncio.create_subprocess_exec(
            str(script_path), "--json", "--push", "--task", "smart-sync",
            cwd=project_root, env=env,
            stdout=aio_subprocess.PIPE, stderr=aio_subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return _parse_smart_sync_output(stdout.decode(), stderr.decode(), proc.returncode or 0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def find_repo_for_sha(commit_sha: str) -> Path | None:
    """Find which managed repo contains the given SHA."""
    for repo_path in get_managed_repos():
        try:
            result = subprocess.run(
                ["git", "cat-file", "-t", commit_sha],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip() == "commit":
                return repo_path
        except (subprocess.TimeoutExpired, OSError):
            continue
    return None


def _validate_sha_in_repo(sha: str, repo_path: Path, project_id: str) -> None:
    """Validate that a SHA exists as a commit in the given repo."""
    try:
        check = subprocess.run(
            ["git", "cat-file", "-t", sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if check.returncode != 0 or check.stdout.strip() != "commit":
            raise HTTPException(
                status_code=404,
                detail=f"Commit {sha} not found in project {project_id}",
            )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise HTTPException(status_code=500, detail="Git lookup failed") from exc


def _get_commit_metadata(sha: str, repo_path: Path) -> tuple[str, list[str]]:
    """Get commit title and list of parent SHAs."""
    try:
        meta_result = subprocess.run(
            ["git", "log", "-1", "--format=%s%n%P", sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if meta_result.returncode == 0:
            lines = meta_result.stdout.strip().split("\n")
            title = lines[0] if lines else sha
            parents = lines[1].split() if len(lines) > 1 and lines[1] else []
            return title, parents
    except (subprocess.TimeoutExpired, OSError) as exc:
        _logger.debug("Failed to get commit metadata", sha=sha, error=str(exc))
    return sha, []


def build_commit_diff_response(
    sha: str,
    repo_path: Path,
    project_id: str | None,
) -> TaskDiffResponse:
    """Build a TaskDiffResponse for a single commit SHA."""
    if project_id:
        _validate_sha_in_repo(sha, repo_path, project_id)
    title, parents = _get_commit_metadata(sha, repo_path)
    base_sha = parents[0] if parents else "4b825dc642cb6eb9a060e54bf899d15363da7b23"
    try:
        files, stats = get_task_diff(repo_path, base_sha, sha)
    except Exception:
        files, stats = [], DiffStats(files_changed=0, additions=0, deletions=0)
    return TaskDiffResponse(
        task_id=sha,
        task_title=title,
        pre_merge_sha=base_sha,
        merge_sha=sha,
        files=files,
        stats=stats,
    )


def build_task_diff_response(task_id: str) -> TaskDiffResponse:
    """Build TaskDiffResponse for a task by its ID."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    pre_sha = task.get("pre_merge_sha")
    merge_sha = task.get("merge_sha")
    if not pre_sha or not merge_sha:
        return TaskDiffResponse(
            task_id=task_id,
            task_title=task.get("title", ""),
            pre_merge_sha=pre_sha,
            merge_sha=merge_sha,
            files=[],
            stats=DiffStats(files_changed=0, additions=0, deletions=0),
        )
    project_root = get_project_path(task["project_id"])
    files, stats = get_task_diff(project_root, pre_sha, merge_sha)
    return TaskDiffResponse(
        task_id=task_id,
        task_title=task.get("title", ""),
        pre_merge_sha=pre_sha,
        merge_sha=merge_sha,
        files=files,
        stats=stats,
    )


def build_recent_merges_response(
    limit: int = 20, project_id: str | None = None
) -> RecentMergesResponse:
    """Build RecentMergesResponse from database and diff computation."""
    rows = query_recent_merges(limit=limit, project_id=project_id)
    merges: list[MergedTaskSummary] = []
    for row in rows:
        try:
            project_root = get_project_path(row["project_id"])
            stats = get_task_diff(project_root, row["pre_sha"], row["merge_sha"])[1]
        except Exception:
            stats = DiffStats(files_changed=0, additions=0, deletions=0)
        merges.append(MergedTaskSummary(
            task_id=row["task_id"],
            task_title=row["title"] or "",
            project_id=row["project_id"] or "",
            merged_at=str(row["completed_at"]) if row["completed_at"] else "",
            files_changed=stats.files_changed,
            additions=stats.additions,
            deletions=stats.deletions,
        ))
    return RecentMergesResponse(merges=merges, count=len(merges))


def build_conflicts_response(project_id: str | None = None) -> list[ConflictInfo]:
    """Build list of ConflictInfo from database."""
    rows = query_conflicts(project_id)
    conflicts: list[ConflictInfo] = []
    for row in rows:
        ci = row["conflict_info"] if isinstance(row["conflict_info"], dict) else {}
        conflicts.append(ConflictInfo(
            task_id=row["task_id"],
            task_title=row["title"] or "",
            project_id=row["project_id"] or "",
            conflicting_files=ci.get("conflicting_files", []),
            task_branch=ci.get("task_branch", ""),
            base_branch=ci.get("base_branch", "main"),
            detected_at=ci.get("detected_at", ""),
            error_output=ci.get("error_output"),
        ))
    return conflicts


def handle_revert_snapshot(task_id: str) -> dict[str, str]:
    """Revert to a pre-merge snapshot for a task."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project_root = get_project_path(task["project_id"])
    snapshots = list_snapshots(project_root)
    target = next((s for s in snapshots if s.task_id == task_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Snapshot not found for this task")
    if target.commits_ahead == 0:
        raise HTTPException(status_code=400, detail="Already at this snapshot point")
    new_sha = revert_to_snapshot(project_root, target.sha, target.commits_ahead)
    if not new_sha:
        raise HTTPException(status_code=500, detail="Revert failed — may have conflicts")
    return {"status": "reverted", "reverted_to": new_sha}


def handle_dismiss_conflict(task_id: str) -> dict[str, str]:
    """Dismiss a merge conflict, moving the task back to failed."""
    from ...storage.tasks.status import update_task_status

    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "failed":
        raise HTTPException(status_code=400, detail="Task is not in failed state")
    update_task_fields(task_id, conflict_info=None)
    update_task_status(
        task_id, "failed",
        error_message="Merge conflict dismissed",
        validate_transition=False,
    )
    return {"status": "dismissed"}


async def build_project_dashboard(
    project_id: str, commits_limit: int = 15
) -> ProjectDashboardResponse:
    """Build project dashboard response."""
    repo_path = get_project_root_with_fallback(project_id)
    checkpoints = [c for c in collect_checkpoints() if c.project_id == project_id]
    branches = get_all_branches(repo_path, project_id=project_id)
    merges_resp = build_recent_merges_response(limit=10, project_id=project_id)
    commits = get_recent_commits(repo_path, limit=commits_limit)
    snapshots = list_snapshots(repo_path)
    enrich_snapshots(snapshots)
    conflicts = build_conflicts_response(project_id=project_id)
    return ProjectDashboardResponse(
        checkpoints=checkpoints,
        branches=branches,
        recent_merges=merges_resp.merges,
        recent_commits=commits,
        snapshots=snapshots,
        conflicts=conflicts,
    )


# --- Conflict resolution helpers ---


def _resolve_conflict_response(
    task_id: str, project_id: str, checkout: Any, files: list[str], status: str
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "status": status,
        "project_id": project_id,
        "checkout_path": str(checkout.path),
        "task_branch": checkout.branch,
        "base_branch": checkout.base_branch,
        "conflicting_files": files,
    }


async def handle_resolve_conflict(task_id: str) -> dict[str, object]:
    """Reopen a residue task and dispatch execution to resolve its merge conflict."""
    from ...services.task_checkout import create_task_checkout, get_task_checkout
    from ...storage import log_task_event
    from ...storage.subtasks import get_subtasks_for_task, update_subtask_passes
    from ...storage.tasks.claims import claim_task
    from ...storage.tasks.status import update_task_status
    from ...tasks.autonomous.cleanup.merge_operations import merge_and_cleanup_task_checkpoint
    from ...workflows.models import TaskInput
    from ...workflows.pipeline import execute_wf

    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    status = str(task.get("status") or "")
    if status != "failed":
        raise HTTPException(
            status_code=400,
            detail=f"Task status {status!r} is not eligible for conflict resolution",
        )
    conflict_info = task.get("conflict_info") or {}
    if (not isinstance(conflict_info, dict) or not conflict_info) and status == "failed":
        merge_result: MergeResult = merge_and_cleanup_task_checkpoint(task_id, str(task["project_id"]))
        if str(merge_result.get("status") or "") != "failed":
            return cast(dict[str, object], merge_result)
        task = task_store.get_task(task_id) or task
        conflict_info = task.get("conflict_info") or {}
    if not isinstance(conflict_info, dict) or not conflict_info:
        raise HTTPException(status_code=400, detail="Task does not have conflict metadata to resolve")

    project_id = str(task["project_id"])
    checkout = get_task_checkout(task_id, project_id) or create_task_checkout(task_id, project_id)
    if not checkout:
        raise HTTPException(status_code=500, detail="Unable to prepare task branch for conflict resolution")
    files = conflict_info.get("conflicting_files") or []
    message = "Resolve merge conflict against current main" + (f" in {', '.join(files[:5])}" if files else "")
    update_task_status(task_id, "failed", error_message=message, validate_transition=False)
    for subtask in get_subtasks_for_task(task_id):
        short_id = str(subtask.get("subtask_id") or "")
        if short_id and subtask.get("passes"):
            update_subtask_passes(task_id, short_id, False)
    log_task_event(task_id, f"Conflict resolution reopened for autocode: {message}")
    worker_id = f"resolve-conflict-{project_id}"
    if not claim_task(task_id, worker_id, lock_duration_minutes=60):
        return _resolve_conflict_response(task_id, project_id, checkout, files, "already_claimed")
    await execute_wf.aio_run_no_wait(TaskInput(task_id=task_id, project_id=project_id))
    return _resolve_conflict_response(task_id, project_id, checkout, files, "dispatched_for_conflict_resolution")


def handle_finalize_task_merge(task_id: str, task: dict[str, Any]) -> MergeResult:
    """Validate status and execute finalize merge/cleanup for a residue task."""
    from ...storage.subtasks import get_subtasks_for_task

    status = str(task.get("status") or "")
    if status in {"running", "pending"}:
        raise HTTPException(
            status_code=400,
            detail=f"Task is still active ({status}); use the normal execution/done path instead",
        )
    if status not in {"completed", "failed"}:
        raise HTTPException(status_code=400, detail=f"Task status {status!r} is not eligible for finalize")
    # Block merge when subtasks have failures — prevents merging incomplete work
    subtasks = get_subtasks_for_task(task_id)
    failed = [s for s in subtasks if s.get("passes") is False]
    if failed:
        failed_ids = [s.get("subtask_id", "?") for s in failed]
        raise HTTPException(
            status_code=400,
            detail=f"Cannot finalize: {len(failed)} subtask(s) failed ({', '.join(failed_ids)}). Fix or skip them first.",
        )
    if status == "failed":
        update_task_fields(task_id, conflict_info=None)
    return merge_and_cleanup_task_checkpoint(task_id, task["project_id"])


# --- Collection helpers ---


def collect_recent_commits(limit: int, project_id: str | None) -> list[CommitInfo]:
    """Collect recent commits across managed repos or for a specific project."""
    if project_id:
        try:
            return list(get_recent_commits(get_project_path(project_id), limit=limit))
        except HTTPException:
            return []
    all_commits: list[CommitInfo] = []
    for repo_path in get_managed_repos():
        all_commits.extend(get_recent_commits(repo_path, limit=limit))
    all_commits.sort(key=lambda c: c.date, reverse=True)
    return all_commits[:limit]


def collect_snapshots(project_id: str | None) -> list[SnapshotInfo]:
    """Collect pre-merge snapshots across managed repos or for a specific project."""
    all_snapshots: list[SnapshotInfo] = []
    if project_id:
        try:
            all_snapshots = list(list_snapshots(get_project_path(project_id)))
            enrich_snapshots(all_snapshots)
        except HTTPException as exc:
            _logger.debug("Snapshot collection failed for project", project_id=project_id, status=exc.status_code)
    else:
        for repo_path in get_managed_repos():
            all_snapshots.extend(list_snapshots(repo_path))
        enrich_snapshots(all_snapshots)
    return all_snapshots
