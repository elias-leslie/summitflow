"""Git management API endpoints."""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from fastapi import APIRouter, HTTPException, Query

from cli.commands.cleanup import build_cleanup_status_payload
from cli.commands.cleanup_display import render_cleanup_status_compact
from cli.lib.checkpoint import get_active_checkpoints

from ..storage import tasks as task_store
from ..storage.tasks.update import update_task_fields
from ..tasks.autonomous.cleanup.merge_operations import merge_and_cleanup_task_checkpoint
from ..utils.git_helpers import (
    get_all_branches,
    get_managed_repos,
    get_repo_status,
    pull_repository,
    push_repository,
    sync_repository,
)
from .git_helpers.checkpoint_helpers import collect_checkpoints
from .git_helpers.db_helpers import (
    get_project_path,
    get_project_root,
    get_project_root_with_fallback,
)
from .git_helpers.endpoints import (
    build_commit_diff_response,
    build_conflicts_response,
    build_project_dashboard,
    build_recent_merges_response,
    build_task_diff_response,
    collect_recent_commits,
    collect_snapshots,
    execute_smart_sync,
    find_repo_for_sha,
    handle_dismiss_conflict,
    handle_finalize_task_merge,
    handle_resolve_conflict,
    handle_revert_snapshot,
)
from .git_helpers.response_builders import aggregate_sync_results, build_sync_response_from_result
from .models.git_models import (
    BranchesResponse,
    CheckpointsResponse,
    ConflictsResponse,
    GitStatusResponse,
    GitSyncResponse,
    ProjectDashboardResponse,
    RecentCommitsResponse,
    RecentMergesResponse,
    RepoStatus,
    SnapshotsResponse,
    TaskDiffResponse,
)

router = APIRouter()


def _build_cleanup_status_response(*, all_projects: bool, project_id: str | None = None) -> dict[str, object]:
    """Return canonical cleanup payload plus compact text."""
    payload = build_cleanup_status_payload(all_projects, project_id_override=project_id)
    return {
        "payload": payload,
        "compact": render_cleanup_status_compact(payload, all_projects),
    }


@router.get("/git/status", response_model=GitStatusResponse, tags=["git"])
async def get_git_status() -> GitStatusResponse:
    """Get git status for all managed repositories."""
    active_checkpoints_by_project: dict[str, list] = defaultdict(list)
    for checkpoint in get_active_checkpoints():
        if checkpoint.project_id:
            active_checkpoints_by_project[checkpoint.project_id].append(checkpoint)

    repos: list[RepoStatus] = []
    for repo_path in get_managed_repos():
        repo_status = get_repo_status(
            repo_path,
            active_checkpoints_by_project=active_checkpoints_by_project,
        )
        if repo_status:
            repos.append(repo_status)
    return GitStatusResponse(repositories=repos, total=len(repos))


@router.get("/git/cleanup-status", tags=["git"])
async def get_cleanup_status() -> dict[str, object]:
    """Get canonical cleanup status across all managed repositories."""
    return _build_cleanup_status_response(all_projects=True)


@router.get(
    "/projects/{project_id}/git/status",
    response_model=GitStatusResponse,
    tags=["git"],
)
async def get_project_git_status(project_id: str) -> GitStatusResponse:
    """Get git status for a specific project's repository."""
    repo_path = get_project_root(project_id)
    repo_status = get_repo_status(repo_path, project_id=project_id)
    if not repo_status:
        return GitStatusResponse(repositories=[], total=0)
    return GitStatusResponse(repositories=[repo_status], total=1)


@router.get("/projects/{project_id}/git/cleanup-status", tags=["git"])
async def get_project_cleanup_status(project_id: str) -> dict[str, object]:
    """Get canonical cleanup status for one managed repository."""
    return _build_cleanup_status_response(all_projects=False, project_id=project_id)


@router.post("/git/sync", response_model=GitSyncResponse, tags=["git"])
async def sync_repositories() -> GitSyncResponse:
    """Sync all managed repositories by pulling from remote."""
    results = [sync_repository(repo_path) for repo_path in get_managed_repos()]
    counts = aggregate_sync_results(results)
    return GitSyncResponse(results=results, **counts)


@router.get("/git/checkpoints", response_model=CheckpointsResponse, tags=["git"])
async def get_checkpoints(
    project_id: str | None = Query(default=None),
) -> CheckpointsResponse:
    """Get list of active task checkpoints, optionally filtered by project."""
    checkpoints = collect_checkpoints()
    if project_id:
        checkpoints = [c for c in checkpoints if c.project_id == project_id]
    return CheckpointsResponse(checkpoints=checkpoints, count=len(checkpoints))


@router.get("/git/branches", response_model=BranchesResponse, tags=["git"])
async def get_branches(
    project_id: str | None = Query(default=None),
) -> BranchesResponse:
    """Get list of branches across managed repos, optionally filtered by project."""
    if project_id:
        repo_path = get_project_root(project_id)
        branches = get_all_branches(repo_path, project_id=project_id)
        return BranchesResponse(branches=branches, count=len(branches))

    branches = [
        branch
        for repo_path in get_managed_repos()
        for branch in get_all_branches(repo_path)
    ]
    branches.sort(key=lambda b: ((b.repo_name or "").lower(), not b.is_current, not b.has_checkpoint, b.name.lower()))
    return BranchesResponse(branches=branches, count=len(branches))


@router.post(
    "/projects/{project_id}/git/pull",
    response_model=GitSyncResponse,
    tags=["git"],
)
async def pull_project_repository(project_id: str) -> GitSyncResponse:
    """Pull changes for a specific project's repository."""
    result = pull_repository(get_project_root(project_id))
    return GitSyncResponse(results=[result], **build_sync_response_from_result(result))


@router.post(
    "/projects/{project_id}/git/push",
    response_model=GitSyncResponse,
    tags=["git"],
)
async def push_project_repository(project_id: str) -> GitSyncResponse:
    """Push changes for a specific project's repository."""
    result = push_repository(get_project_root(project_id))
    return GitSyncResponse(results=[result], **build_sync_response_from_result(result))


@router.post(
    "/projects/{project_id}/git/fetch",
    response_model=GitSyncResponse,
    tags=["git"],
)
async def fetch_project_repository(project_id: str) -> GitSyncResponse:
    """Fetch changes for a specific project's repository."""
    from ..utils.git_helpers import fetch_repository

    result = fetch_repository(get_project_root(project_id))
    return GitSyncResponse(results=[result], **build_sync_response_from_result(result))


@router.post("/projects/{project_id}/git/smart-sync", tags=["git"])
async def smart_sync_project(project_id: str) -> dict[str, object]:
    """Smart Sync: Check gates -> AI Commit -> Pull -> Push."""
    return await execute_smart_sync(get_project_root_with_fallback(project_id))


# --- Conflict Endpoints ---


@router.get("/git/conflicts", response_model=ConflictsResponse, tags=["git"])
async def get_conflicts(
    project_id: str | None = Query(default=None),
) -> ConflictsResponse:
    """Get all tasks with active merge conflicts, optionally filtered by project."""
    conflicts = build_conflicts_response(project_id)
    return ConflictsResponse(conflicts=conflicts, count=len(conflicts))


@router.post("/git/tasks/{task_id}/retry-merge", tags=["git"])
async def retry_merge(task_id: str) -> dict[str, object]:
    """Retry merging a conflicted task."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "failed":
        raise HTTPException(status_code=400, detail="Task is not in failed state")
    update_task_fields(task_id, conflict_info=None)
    return cast(dict[str, object], merge_and_cleanup_task_checkpoint(task_id, task["project_id"]))


@router.post("/git/tasks/{task_id}/resolve-conflict", tags=["git"])
async def resolve_conflict(task_id: str) -> dict[str, object]:
    """Reopen a residue task and dispatch execution to resolve its merge conflict."""
    return await handle_resolve_conflict(task_id)


@router.post("/git/tasks/{task_id}/finalize", tags=["git"])
async def finalize_task_merge(task_id: str) -> dict[str, object]:
    """Finalize merge/cleanup for a residue task checkpoint that is no longer actively executing."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return cast(dict[str, object], handle_finalize_task_merge(task_id, task))


@router.post("/git/tasks/{task_id}/dismiss-conflict", tags=["git"])
async def dismiss_conflict(task_id: str) -> dict[str, str]:
    """Dismiss a merge conflict, moving the task back to failed."""
    return handle_dismiss_conflict(task_id)


# --- Diff / Merge Review Endpoints ---


@router.get("/tasks/{task_id}/diff", response_model=TaskDiffResponse, tags=["git"])
async def get_task_diff_endpoint(task_id: str) -> TaskDiffResponse:
    """Get the full diff for a merged task."""
    return build_task_diff_response(task_id)


@router.get("/git/recent-merges", response_model=RecentMergesResponse, tags=["git"])
async def get_recent_merges(
    limit: int = Query(default=20, le=100),
    project_id: str | None = Query(default=None),
) -> RecentMergesResponse:
    """Get recently merged tasks with diff stats, optionally filtered by project."""
    return build_recent_merges_response(limit=limit, project_id=project_id)


# --- Single Commit Diff Endpoint ---


@router.get(
    "/git/commits/{sha}/diff",
    response_model=TaskDiffResponse,
    tags=["git"],
)
async def get_commit_diff(
    sha: str,
    project_id: str | None = Query(default=None),
) -> TaskDiffResponse:
    """Get the diff for a single commit by SHA."""
    if project_id:
        repo_path = get_project_path(project_id)
    else:
        repo_path = find_repo_for_sha(sha)
        if not repo_path:
            raise HTTPException(
                status_code=404, detail=f"Commit {sha} not found in any managed repo"
            )
    return build_commit_diff_response(sha, repo_path, project_id)


# --- Commit History Endpoints ---


@router.get("/git/commits/recent", response_model=RecentCommitsResponse, tags=["git"])
async def get_recent_commits_endpoint(
    limit: int = Query(default=50, le=200),
    project_id: str | None = Query(default=None),
) -> RecentCommitsResponse:
    """Get recent commits across all managed repos (or a specific project)."""
    commits = collect_recent_commits(limit, project_id)
    return RecentCommitsResponse(commits=commits, count=len(commits))


# --- Snapshot Endpoints ---


@router.get("/git/snapshots", response_model=SnapshotsResponse, tags=["git"])
async def get_snapshots(
    project_id: str | None = Query(default=None),
) -> SnapshotsResponse:
    """Get pre-merge snapshots across managed repos."""
    snapshots = collect_snapshots(project_id)
    return SnapshotsResponse(snapshots=snapshots, count=len(snapshots))


@router.post("/git/snapshots/{task_id}/revert", tags=["git"])
async def revert_snapshot(task_id: str) -> dict[str, str]:
    """Revert to a pre-merge snapshot (uses git revert to preserve history)."""
    return handle_revert_snapshot(task_id)


# --- Project Dashboard Endpoint ---


@router.get(
    "/git/projects/{project_id}/dashboard",
    response_model=ProjectDashboardResponse,
    tags=["git"],
)
async def get_project_dashboard(
    project_id: str,
    commits_limit: int = Query(default=15, le=100),
) -> ProjectDashboardResponse:
    """Get combined dashboard data for a single project."""
    return await build_project_dashboard(project_id, commits_limit)
