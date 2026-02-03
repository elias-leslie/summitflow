"""Git API models."""

from __future__ import annotations

from pydantic import BaseModel


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


class WorktreeInfo(BaseModel):
    """Information about a worktree."""

    task_id: str
    path: str
    branch: str
    base_branch: str
    is_active: bool


class WorktreesResponse(BaseModel):
    """Response for worktrees list."""

    worktrees: list[WorktreeInfo]
    count: int


class BranchInfo(BaseModel):
    """Information about a git branch."""

    name: str
    is_current: bool
    has_worktree: bool
    worktree_path: str | None = None
    task_id: str | None = None
    last_commit_short: str | None = None
    last_commit_date: str | None = None


class BranchesResponse(BaseModel):
    """Response for branches list."""

    branches: list[BranchInfo]
    count: int
