"""Git management API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..utils.git_helpers import (
    WORKTREES_BASE_DIR,
    fetch_repository,
    get_all_branches,
    get_managed_repos,
    get_repo_status,
    get_worktree_info,
    pull_repository,
    push_repository,
    sync_repository,
)
from .git_helpers.db_helpers import get_project_root, get_project_root_with_fallback
from .git_helpers.endpoints import (
    execute_smart_sync,
)
from .git_helpers.response_builders import aggregate_sync_results, build_sync_response_from_result
from .models.git_models import (
    BranchesResponse,
    GitStatusResponse,
    GitSyncResponse,
    RepoStatus,
    WorktreeInfo,
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
    managed_repos = get_managed_repos()
    if not managed_repos:
        return BranchesResponse(branches=[], count=0)

    # Use the first managed repo for now (typically the main project)
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
async def smart_sync_project(project_id: str) -> dict[str, Any]:
    """Smart Sync: Check gates -> AI Commit -> Pull -> Push."""
    repo_path = get_project_root_with_fallback(project_id)
    return await execute_smart_sync(repo_path)
