"""Git management API endpoints."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.git_service import auto_create_pr
from ..services.worktree_manager import get_worktree_manager
from ..storage import tasks as task_store

router = APIRouter()


# Known managed repositories
MANAGED_REPOS = [
    Path.home() / "summitflow",
    Path.home() / ".claude",
]


class RepoStatus(BaseModel):
    """Status of a git repository."""

    path: str
    name: str
    branch: str
    uncommitted: int
    ahead: int
    behind: int
    state: str  # clean, dirty, behind, ahead


class GitStatusResponse(BaseModel):
    """Response for git status."""

    repositories: list[RepoStatus]
    total: int


class SyncResult(BaseModel):
    """Result of syncing a repository."""

    path: str
    name: str
    branch: str
    status: str  # up_to_date, updated, skipped, failed
    reason: str | None = None
    error: str | None = None


class GitSyncResponse(BaseModel):
    """Response for git sync."""

    results: list[SyncResult]
    success: int
    failed: int
    skipped: int


class WorktreeInfo(BaseModel):
    """Information about a worktree."""

    task_id: str
    project_id: str
    branch: str
    path: str
    commit_count: int
    files_changed: int
    additions: int
    deletions: int


class WorktreesResponse(BaseModel):
    """Response for worktree list."""

    worktrees: list[WorktreeInfo]
    total: int


class PRCreateRequest(BaseModel):
    """Request to create a PR."""

    title: str | None = None
    body: str | None = None


class PRResponse(BaseModel):
    """Response for PR operations."""

    pr_url: str
    branch_name: str
    task_id: str


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _get_repo_status(repo_path: Path) -> RepoStatus | None:
    """Get status information for a git repository."""
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return None

    # Get current branch
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()

    # Get uncommitted changes count
    result = _run_git(["status", "--porcelain"], repo_path)
    uncommitted = 0
    if result.returncode == 0:
        lines = [line for line in result.stdout.strip().split("\n") if line]
        uncommitted = len(lines)

    # Get ahead/behind counts
    ahead = 0
    behind = 0
    result = _run_git(
        ["rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"],
        repo_path,
    )
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            ahead = int(parts[0])
            behind = int(parts[1])

    # Determine overall state
    if uncommitted > 0:
        state = "dirty"
    elif behind > 0:
        state = "behind"
    elif ahead > 0:
        state = "ahead"
    else:
        state = "clean"

    return RepoStatus(
        path=str(repo_path),
        name=repo_path.name,
        branch=branch,
        uncommitted=uncommitted,
        ahead=ahead,
        behind=behind,
        state=state,
    )


@router.get("/git/status", response_model=GitStatusResponse, tags=["git"])
async def get_git_status() -> GitStatusResponse:
    """Get git status for all managed repositories."""
    repos: list[RepoStatus] = []

    for repo_path in MANAGED_REPOS:
        repo_status = _get_repo_status(repo_path)
        if repo_status:
            repos.append(repo_status)

    return GitStatusResponse(repositories=repos, total=len(repos))


@router.post("/git/sync", response_model=GitSyncResponse, tags=["git"])
async def sync_repositories() -> GitSyncResponse:
    """Sync all managed repositories by pulling from remote.

    Skips repositories with uncommitted changes.
    """
    results: list[SyncResult] = []
    success = 0
    failed = 0
    skipped = 0

    for repo_path in MANAGED_REPOS:
        repo_status = _get_repo_status(repo_path)
        if not repo_status:
            continue

        result = SyncResult(
            path=str(repo_path),
            name=repo_path.name,
            branch=repo_status.branch,
            status="unknown",
        )

        # Skip dirty repos
        if repo_status.uncommitted > 0:
            result.status = "skipped"
            result.reason = "uncommitted changes"
            skipped += 1
            results.append(result)
            continue

        # Pull from remote
        git_result = _run_git(["pull", "--ff-only"], repo_path)

        if git_result.returncode == 0:
            if "Already up to date" in git_result.stdout:
                result.status = "up_to_date"
            else:
                result.status = "updated"
            success += 1
        else:
            result.status = "failed"
            result.error = git_result.stderr.strip()
            failed += 1

        results.append(result)

    return GitSyncResponse(
        results=results,
        success=success,
        failed=failed,
        skipped=skipped,
    )


@router.get(
    "/projects/{project_id}/worktrees",
    response_model=WorktreesResponse,
    tags=["git"],
)
async def list_worktrees(project_id: str) -> WorktreesResponse:
    """List all active worktrees for a project."""
    from ..storage.connection import get_connection

    # Get project root from database
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        project_root = row[0]

    if not project_root:
        raise HTTPException(status_code=400, detail="Project has no root_path configured")

    manager = get_worktree_manager(Path(project_root))
    worktrees_list = manager.list_active_worktrees(project_id=project_id)

    return WorktreesResponse(
        worktrees=[
            WorktreeInfo(
                task_id=wt.task_id,
                project_id=wt.project_id,
                branch=wt.branch,
                path=str(wt.path),
                commit_count=wt.commit_count,
                files_changed=wt.files_changed,
                additions=wt.additions,
                deletions=wt.deletions,
            )
            for wt in worktrees_list
        ],
        total=len(worktrees_list),
    )


@router.delete(
    "/projects/{project_id}/worktrees/{task_id}",
    tags=["git"],
)
async def delete_worktree(project_id: str, task_id: str) -> dict[str, Any]:
    """Delete a worktree for a task."""
    from ..storage.connection import get_connection

    # Get project root from database
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        project_root = row[0]

    if not project_root:
        raise HTTPException(status_code=400, detail="Project has no root_path configured")

    manager = get_worktree_manager(Path(project_root))

    # Check if worktree exists
    if not manager.worktree_exists(project_id, task_id):
        raise HTTPException(status_code=404, detail=f"Worktree for task {task_id} not found")

    manager.remove_worktree(project_id, task_id, delete_branch=True)

    return {"success": True, "message": f"Worktree for task {task_id} deleted"}


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
