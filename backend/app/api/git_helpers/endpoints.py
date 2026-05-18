"""Complex endpoint logic for git operations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.tasks.update import update_task_fields
from ...utils import safe_subprocess
from ...utils.git_helpers import (
    enrich_branch_cleanup_details,
    get_all_branches,
    get_managed_repos,
    get_recent_commits,
    get_task_diff,
    list_snapshots,
    revert_to_snapshot,
)
from ...utils.shared_paths import get_repo_root
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


def _project_publish_env() -> tuple[list[str], dict[str, str] | None]:
    """Return (command prefix, env) for the st commit project publish invocation."""
    host_root = os.environ.get("BACKUP_HOST_ROOT")
    st_path = shutil.which("st") or str(get_repo_root() / "backend" / ".venv" / "bin" / "st")
    if not host_root:
        return [st_path, "--no-compact", "commit"], None

    env = os.environ.copy()
    env["HOME"] = host_root
    host_bin_dirs = [f"{host_root}/.local/bin", f"{host_root}/bin", f"{host_root}/.cargo/bin"]
    env["PATH"] = ":".join(host_bin_dirs) + ":" + env.get("PATH", "")
    ssh_dir = f"{host_root}/.ssh"
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {ssh_dir}/id_ed25519 -o UserKnownHostsFile={ssh_dir}/known_hosts"
    )
    return ["st", "--no-compact", "commit"], env


def _parse_project_publish_output(output: str, stderr_text: str, returncode: int) -> dict[str, Any]:
    """Parse st commit JSON output into a normalized response dict."""
    raw_output = output + stderr_text
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        data = _extract_project_publish_json(raw_output)
        if data is None:
            return {
                "success": False,
                "status": "UNKNOWN",
                "gates": "",
                "errors": [stderr_text[:200]],
                "message": "",
                "reason": "json_parse_failed",
                "detail": stderr_text[:200],
                "pushed": False,
                "raw_output": raw_output,
            }
    repo_data = data.get("repos", [{}])[0] if data.get("repos") else data
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
        "raw_output": raw_output,
    }


def _extract_project_publish_json(raw_output: str) -> dict[str, Any] | None:
    """Extract the first JSON object from output mixed with warnings/log lines."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw_output):
        if char != "{":
            continue
        try:
            data, _end = decoder.raw_decode(raw_output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


async def execute_project_publish(project_root: Path) -> dict[str, Any]:
    """Publish project work using st commit."""
    import asyncio

    command_prefix, env = _project_publish_env()
    try:
        result = await asyncio.to_thread(
            safe_subprocess.run,
            [
                *command_prefix,
                "--push",
                "--bookmark",
                "main",
                "--message",
                "publish project work",
                "-R",
                str(project_root),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        return _parse_project_publish_output(result.stdout, result.stderr, result.returncode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def find_repo_for_sha(commit_sha: str) -> Path | None:
    """Find which managed repo contains the given SHA."""
    for repo_path in get_managed_repos():
        try:
            result = safe_subprocess.run(
                ["git", "-C", str(repo_path), "cat-file", "-t", commit_sha],
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
        check = safe_subprocess.run(
            ["git", "-C", str(repo_path), "cat-file", "-t", sha],
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
        meta_result = safe_subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%s%n%P", sha],
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
    branches = enrich_branch_cleanup_details(
        repo_path,
        get_all_branches(repo_path, project_id=project_id),
    )
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
