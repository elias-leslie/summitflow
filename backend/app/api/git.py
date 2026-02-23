"""Git management API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..storage import tasks as task_store
from ..storage.connection import get_connection
from ..storage.tasks.update import update_task_fields
from ..tasks.autonomous.cleanup.merge_operations import merge_and_cleanup_task_worktree
from ..utils.git_helpers import (
    WORKTREES_BASE_DIR,
    fetch_repository,
    get_all_branches,
    get_managed_repos,
    get_recent_commits,
    get_repo_status,
    get_task_diff,
    get_worktree_info,
    list_snapshots,
    pull_repository,
    push_repository,
    revert_to_snapshot,
    sync_repository,
)
from .git_helpers.db_helpers import get_project_root, get_project_root_with_fallback
from .git_helpers.endpoints import execute_smart_sync
from .git_helpers.response_builders import aggregate_sync_results, build_sync_response_from_result
from .models.git_models import (
    BranchesResponse,
    ConflictInfo,
    ConflictsResponse,
    DiffStats,
    GitStatusResponse,
    GitSyncResponse,
    MergedTaskSummary,
    RecentCommitsResponse,
    RecentMergesResponse,
    RepoStatus,
    SnapshotsResponse,
    TaskDiffResponse,
    WorktreeInfo,
    WorktreesResponse,
)

router = APIRouter()


def _collect_worktrees() -> list[WorktreeInfo]:
    """Collect worktree info from the base directory."""
    if not WORKTREES_BASE_DIR.exists():
        return []
    worktrees: list[WorktreeInfo] = []
    for entry in WORKTREES_BASE_DIR.iterdir():
        if not entry.is_dir():
            continue
        info = get_worktree_info(entry.name)
        if info:
            worktrees.append(info)
    return worktrees


@router.get("/git/status", response_model=GitStatusResponse, tags=["git"])
async def get_git_status() -> GitStatusResponse:
    """Get git status for all managed repositories."""
    repos: list[RepoStatus] = []
    for repo_path in get_managed_repos():
        repo_status = get_repo_status(repo_path)
        if repo_status:
            repos.append(repo_status)
    return GitStatusResponse(repositories=repos, total=len(repos))


@router.get(
    "/projects/{project_id}/git/status",
    response_model=GitStatusResponse,
    tags=["git"],
)
async def get_project_git_status(project_id: str) -> GitStatusResponse:
    """Get git status for a specific project's repository."""
    repo_path = get_project_root(project_id)
    repo_status = get_repo_status(repo_path)
    if not repo_status:
        return GitStatusResponse(repositories=[], total=0)
    return GitStatusResponse(repositories=[repo_status], total=1)


@router.post("/git/sync", response_model=GitSyncResponse, tags=["git"])
async def sync_repositories() -> GitSyncResponse:
    """Sync all managed repositories by pulling from remote.

    Skips repositories with uncommitted changes.
    """
    results = [sync_repository(repo_path) for repo_path in get_managed_repos()]
    counts = aggregate_sync_results(results)
    return GitSyncResponse(results=results, **counts)


@router.get("/git/worktrees", response_model=WorktreesResponse, tags=["git"])
async def get_worktrees() -> WorktreesResponse:
    """Get list of active worktrees."""
    worktrees = _collect_worktrees()
    return WorktreesResponse(worktrees=worktrees, count=len(worktrees))


@router.get("/git/branches", response_model=BranchesResponse, tags=["git"])
async def get_branches() -> BranchesResponse:
    """Get list of all branches with worktree indicators.

    Returns local and remote branches with information about:
    - Whether it's the current branch
    - Whether it has an associated worktree
    - Last commit info
    """
    managed_repos = get_managed_repos()
    if not managed_repos:
        return BranchesResponse(branches=[], count=0)
    branches = get_all_branches(managed_repos[0])
    return BranchesResponse(branches=branches, count=len(branches))


@router.post(
    "/projects/{project_id}/git/pull",
    response_model=GitSyncResponse,
    tags=["git"],
)
async def pull_project_repository(project_id: str) -> GitSyncResponse:
    """Pull changes for a specific project's repository."""
    repo_path = get_project_root(project_id)
    result = pull_repository(repo_path)
    counts = build_sync_response_from_result(result)
    return GitSyncResponse(results=[result], **counts)


@router.post(
    "/projects/{project_id}/git/push",
    response_model=GitSyncResponse,
    tags=["git"],
)
async def push_project_repository(project_id: str) -> GitSyncResponse:
    """Push changes for a specific project's repository."""
    repo_path = get_project_root(project_id)
    result = push_repository(repo_path)
    counts = build_sync_response_from_result(result)
    return GitSyncResponse(results=[result], **counts)


@router.post(
    "/projects/{project_id}/git/fetch",
    response_model=GitSyncResponse,
    tags=["git"],
)
async def fetch_project_repository(project_id: str) -> GitSyncResponse:
    """Fetch changes for a specific project's repository."""
    repo_path = get_project_root(project_id)
    result = fetch_repository(repo_path)
    counts = build_sync_response_from_result(result)
    return GitSyncResponse(results=[result], **counts)


@router.post("/projects/{project_id}/git/smart-sync", tags=["git"])
async def smart_sync_project(project_id: str) -> dict[str, object]:
    """Smart Sync: Check gates -> AI Commit -> Pull -> Push."""
    repo_path = get_project_root_with_fallback(project_id)
    return await execute_smart_sync(repo_path)


# --- Conflict Endpoints ---


@router.get("/git/conflicts", response_model=ConflictsResponse, tags=["git"])
async def get_conflicts() -> ConflictsResponse:
    """Get all tasks with active merge conflicts."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, project_id, conflict_info
               FROM tasks
               WHERE status = 'conflicted' AND conflict_info IS NOT NULL
               ORDER BY completed_at DESC NULLS LAST"""
        )
        rows = cur.fetchall()

    conflicts: list[ConflictInfo] = []
    for row in rows:
        task_id, title, project_id, info = row
        if not info:
            continue
        # info is already a dict from JSONB
        ci = info if isinstance(info, dict) else {}
        conflicts.append(ConflictInfo(
            task_id=task_id,
            task_title=title or "",
            project_id=project_id or "",
            conflicting_files=ci.get("conflicting_files", []),
            task_branch=ci.get("task_branch", ""),
            base_branch=ci.get("base_branch", "main"),
            detected_at=ci.get("detected_at", ""),
            error_output=ci.get("error_output"),
        ))

    return ConflictsResponse(conflicts=conflicts, count=len(conflicts))


@router.post("/git/tasks/{task_id}/retry-merge", tags=["git"])
async def retry_merge(task_id: str) -> dict[str, object]:
    """Retry merging a conflicted task."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "conflicted":
        raise HTTPException(status_code=400, detail="Task is not in conflicted state")

    project_id = task["project_id"]

    # Clear conflict info before retry
    update_task_fields(task_id, conflict_info=None)

    # Re-attempt the merge
    result: dict[str, object] = merge_and_cleanup_task_worktree(task_id, project_id)  # type: ignore[assignment]
    return result


@router.post("/git/tasks/{task_id}/dismiss-conflict", tags=["git"])
async def dismiss_conflict(task_id: str) -> dict[str, str]:
    """Dismiss a merge conflict, moving the task back to failed."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "conflicted":
        raise HTTPException(status_code=400, detail="Task is not in conflicted state")

    from ..storage.tasks.status import update_task_status

    update_task_fields(task_id, conflict_info=None)
    update_task_status(
        task_id, "failed",
        error_message="Merge conflict dismissed",
        validate_transition=False,
    )
    return {"status": "dismissed"}


# --- Diff / Merge Review Endpoints ---


@router.get("/tasks/{task_id}/diff", response_model=TaskDiffResponse, tags=["git"])
async def get_task_diff_endpoint(task_id: str) -> TaskDiffResponse:
    """Get the full diff for a merged task."""
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

    project_id = task["project_id"]
    project_root = _get_project_path(project_id)

    files, stats = get_task_diff(project_root, pre_sha, merge_sha)

    return TaskDiffResponse(
        task_id=task_id,
        task_title=task.get("title", ""),
        pre_merge_sha=pre_sha,
        merge_sha=merge_sha,
        files=files,
        stats=stats,
    )


@router.get("/git/recent-merges", response_model=RecentMergesResponse, tags=["git"])
async def get_recent_merges(
    limit: int = Query(default=20, le=100),
) -> RecentMergesResponse:
    """Get recently merged tasks with diff stats."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, project_id, completed_at, pre_merge_sha, merge_sha
               FROM tasks
               WHERE status = 'completed'
                 AND merge_sha IS NOT NULL
                 AND pre_merge_sha IS NOT NULL
               ORDER BY completed_at DESC NULLS LAST
               LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    merges: list[MergedTaskSummary] = []
    for row in rows:
        task_id, title, project_id, completed_at, pre_sha, merge_sha = row
        # Get diff stats for this merge
        try:
            project_root = _get_project_path(project_id)
            stats = get_task_diff(project_root, pre_sha, merge_sha)[1]
        except Exception:
            stats = DiffStats(files_changed=0, additions=0, deletions=0)

        merges.append(MergedTaskSummary(
            task_id=task_id,
            task_title=title or "",
            project_id=project_id or "",
            merged_at=str(completed_at) if completed_at else "",
            files_changed=stats.files_changed,
            additions=stats.additions,
            deletions=stats.deletions,
        ))

    return RecentMergesResponse(merges=merges, count=len(merges))


# --- Commit History Endpoints ---


@router.get("/git/commits/recent", response_model=RecentCommitsResponse, tags=["git"])
async def get_recent_commits_endpoint(
    limit: int = Query(default=50, le=200),
    project_id: str | None = Query(default=None),
) -> RecentCommitsResponse:
    """Get recent commits across all managed repos (or a specific project)."""
    if project_id:
        try:
            repo_path = _get_project_path(project_id)
            all_commits = get_recent_commits(repo_path, limit=limit)
        except HTTPException:
            all_commits = []
    else:
        all_commits = []
        for repo_path in get_managed_repos():
            all_commits.extend(get_recent_commits(repo_path, limit=limit))
        # Sort by date descending, take top N
        all_commits.sort(key=lambda c: c.date, reverse=True)
        all_commits = all_commits[:limit]

    return RecentCommitsResponse(commits=all_commits, count=len(all_commits))


# --- Snapshot Endpoints ---


@router.get("/git/snapshots", response_model=SnapshotsResponse, tags=["git"])
async def get_snapshots(
    project_id: str | None = Query(default=None),
) -> SnapshotsResponse:
    """Get pre-merge snapshots across managed repos."""
    all_snapshots = []

    if project_id:
        try:
            repo_path = _get_project_path(project_id)
            all_snapshots = list_snapshots(repo_path)
            # Enrich with task titles
            _enrich_snapshots(all_snapshots, project_id)
        except HTTPException:
            pass
    else:
        for repo_path in get_managed_repos():
            snapshots = list_snapshots(repo_path)
            all_snapshots.extend(snapshots)
        _enrich_snapshots(all_snapshots)

    return SnapshotsResponse(snapshots=all_snapshots, count=len(all_snapshots))


@router.post("/git/snapshots/{task_id}/revert", tags=["git"])
async def revert_snapshot(task_id: str) -> dict[str, str]:
    """Revert to a pre-merge snapshot (uses git revert to preserve history)."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    project_id = task["project_id"]
    project_root = _get_project_path(project_id)

    # Find the snapshot for this task
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


# --- Helpers ---


def _get_project_path(project_id: str) -> Path:
    """Get project root path, raising HTTPException if not found."""
    from ..storage.projects import get_project_root_path

    path = get_project_root_path(project_id)
    if not path:
        raise HTTPException(status_code=404, detail=f"Project root not found: {project_id}")
    return Path(path)


def _enrich_snapshots(
    snapshots: list, project_id: str | None = None,
) -> None:
    """Enrich snapshot objects with task titles from the database."""
    if not snapshots:
        return
    task_ids = [s.task_id for s in snapshots]
    placeholders = ",".join(["%s"] * len(task_ids))

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id, title, project_id FROM tasks WHERE id IN ({placeholders})",
            tuple(task_ids),
        )
        task_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    for s in snapshots:
        if s.task_id in task_map:
            s.task_title = task_map[s.task_id][0] or ""
            s.project_id = task_map[s.task_id][1] or ""
