"""Git management API endpoints."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.git_service import auto_create_pr
from ..storage import tasks as task_store

router = APIRouter()

# Config repos always included (not SummitFlow projects)
CONFIG_REPOS = [Path.home() / ".claude"]


def _get_managed_repos() -> list[Path]:
    """Get list of managed repos from database + config repos.

    Returns:
        List of Path objects for repos with valid .git directories.
    """
    from ..storage.connection import get_connection

    repos: list[Path] = []

    # Get project root paths from database
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT root_path FROM projects WHERE root_path IS NOT NULL")
            for row in cur.fetchall():
                path = Path(row[0])
                if path.exists() and (path / ".git").exists():
                    repos.append(path)
    except Exception:
        pass

    # Always include config repos
    for config_repo in CONFIG_REPOS:
        if config_repo.exists() and (config_repo / ".git").exists() and config_repo not in repos:
            repos.append(config_repo)

    return repos


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

    for repo_path in _get_managed_repos():
        repo_status = _get_repo_status(repo_path)
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
    repo_status = _get_repo_status(repo_path)

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

    for repo_path in _get_managed_repos():
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
