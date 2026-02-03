"""Git management API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..services.git_service import auto_create_pr
from ..storage import tasks as task_store
from ..utils.git_helpers import (
    WORKTREES_BASE_DIR,
    get_all_branches,
    get_managed_repos,
    get_repo_status,
    get_worktree_info,
    sync_repository,
)
from .models.git_models import (
    BranchesResponse,
    GitStatusResponse,
    GitSyncResponse,
    PRCreateRequest,
    PRResponse,
    RepoStatus,
    SyncResult,
    WorktreesResponse,
)

router = APIRouter()


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
    from ..storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        project_root = row[0]

    if not project_root:
        raise HTTPException(status_code=400, detail="Project has no root_path configured")

    repo_path = Path(project_root)
    repo_status = get_repo_status(repo_path)

    if not repo_status:
        return GitStatusResponse(repositories=[], total=0)

    return GitStatusResponse(repositories=[repo_status], total=1)


@router.post("/git/sync", response_model=GitSyncResponse, tags=["git"])
async def sync_repositories() -> GitSyncResponse:
    """Sync all managed repositories by pulling from remote.

    Skips repositories with uncommitted changes.
    """
    results: list[SyncResult] = []
    success = 0
    failed = 0
    skipped = 0

    for repo_path in get_managed_repos():
        result = sync_repository(repo_path)
        results.append(result)

        if result.status in ["up_to_date", "updated"]:
            success += 1
        elif result.status == "failed":
            failed += 1
        elif result.status == "skipped":
            skipped += 1

    return GitSyncResponse(
        results=results,
        success=success,
        failed=failed,
        skipped=skipped,
    )


@router.post(
    "/tasks/{task_id}/pr",
    response_model=PRResponse,
    tags=["git"],
)
async def create_pull_request(task_id: str, request: PRCreateRequest) -> PRResponse:
    """Create a pull request from the task's branch."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Get project root
    project_id = task.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="Task has no project_id")

    from ..storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=400, detail="Project has no root_path configured")
        project_root = row[0]

    # Create PR
    try:
        result = auto_create_pr(
            task_id=task_id,
            project_path=project_root,
            title=request.title,
            body=request.body,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return PRResponse(
        pr_url=result["pr_url"],
        branch_name=result["branch_name"],
        task_id=task_id,
    )


@router.get(
    "/tasks/{task_id}/pr",
    tags=["git"],
)
async def get_pr_status(task_id: str) -> dict[str, Any]:
    """Get the pull request status for a task."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    pr_url = task.get("pull_request_url")
    if not pr_url:
        return {
            "task_id": task_id,
            "has_pr": False,
            "pr_url": None,
            "branch_name": task.get("branch_name"),
        }

    return {
        "task_id": task_id,
        "has_pr": True,
        "pr_url": pr_url,
        "branch_name": task.get("branch_name"),
        "status": task.get("status"),
    }


@router.get("/git/worktrees", response_model=WorktreesResponse, tags=["git"])
async def get_worktrees() -> WorktreesResponse:
    """Get list of active worktrees."""
    from .models.git_models import WorktreeInfo

    worktrees: list[WorktreeInfo] = []

    if WORKTREES_BASE_DIR.exists():
        for entry in WORKTREES_BASE_DIR.iterdir():
            if entry.is_dir():
                info = get_worktree_info(entry.name)
                if info:
                    worktrees.append(info)

    return WorktreesResponse(worktrees=worktrees, count=len(worktrees))


@router.get("/git/branches", response_model=BranchesResponse, tags=["git"])
async def get_branches() -> BranchesResponse:
    """Get list of all branches with worktree indicators.

    Returns local and remote branches with information about:
    - Whether it's the current branch
    - Whether it has an associated worktree
    - Last commit info
    """
    # Get all managed repos and aggregate branches
    managed_repos = get_managed_repos()
    if not managed_repos:
        return BranchesResponse(branches=[], count=0)

    # Use the first managed repo for now (typically the main project)
    repo_path = managed_repos[0]

    branches = get_all_branches(repo_path)

    return BranchesResponse(branches=branches, count=len(branches))
