"""Git API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepoStatus(BaseModel):
    """Status of a git repository."""

    path: str
    name: str
    project_id: str | None = None
    branch: str
    uncommitted: int
    ahead: int
    behind: int
    state: str  # clean, dirty, behind, ahead
    workspace_summary: RepoWorkspaceSummary | None = None


class OrphanBranchSummary(BaseModel):
    """Actionable cleanup detail for an orphan task branch."""

    branch_name: str
    task_id: str
    resolution: str
    task_status: str | None = None
    commits_ahead: int = 0
    commits_behind: int = 0
    files_changed: int = 0
    has_node_modules_artifact: bool = False


class RepoWorkspaceSummary(BaseModel):
    """At-a-glance branch/checkpoint cleanup summary for one repository."""

    active_checkpoints: int = 0
    dirty_checkpoints: int = 0
    dirty_main_repo: bool = False
    branches_with_checkpoints: int = 0
    orphan_branches: int = 0
    prunable_branches: int = 0
    needs_cleanup: bool = False
    checkpoint_task_ids: list[str] = Field(default_factory=list)
    orphan_branch_names: list[str] = Field(default_factory=list)
    prunable_branch_names: list[str] = Field(default_factory=list)
    salvage_task_ids: list[str] = Field(default_factory=list)
    review_orphan_task_ids: list[str] = Field(default_factory=list)
    orphan_details: list[OrphanBranchSummary] = Field(default_factory=list)


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


class CheckpointInfo(BaseModel):
    """Information about an active task checkpoint."""

    task_id: str
    base_branch: str
    is_active: bool
    project_id: str | None = None


class CheckpointsResponse(BaseModel):
    """Response for checkpoint list."""

    checkpoints: list[CheckpointInfo]
    count: int


class BranchInfo(BaseModel):
    """Information about a git branch."""

    name: str
    is_current: bool
    has_checkpoint: bool
    repo_name: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    last_commit_short: str | None = None
    last_commit_date: str | None = None
    cleanup_resolution: str | None = None
    task_status: str | None = None
    commits_ahead: int | None = None
    commits_behind: int | None = None
    files_changed: int | None = None
    has_node_modules_artifact: bool = False


class BranchesResponse(BaseModel):
    """Response for branches list."""

    branches: list[BranchInfo]
    count: int


# --- Conflict Models ---


class ConflictInfo(BaseModel):
    """Information about a merge conflict on a task."""

    task_id: str
    task_title: str
    project_id: str
    conflicting_files: list[str]
    base_branch: str
    detected_at: str
    error_output: str | None = None


class ConflictsResponse(BaseModel):
    """Response for listing active conflicts."""

    conflicts: list[ConflictInfo]
    count: int


# --- Diff / Merge Models ---


class DiffFile(BaseModel):
    """A single file's diff information."""

    path: str
    status: str  # added, modified, deleted, renamed
    additions: int
    deletions: int
    diff_content: str


class DiffStats(BaseModel):
    """Aggregate diff statistics."""

    files_changed: int
    additions: int
    deletions: int


class TaskDiffResponse(BaseModel):
    """Full diff for a merged task."""

    task_id: str
    task_title: str
    pre_merge_sha: str | None
    merge_sha: str | None
    files: list[DiffFile]
    stats: DiffStats


class MergedTaskSummary(BaseModel):
    """Summary of a recently merged task."""

    task_id: str
    task_title: str
    project_id: str
    merged_at: str
    files_changed: int
    additions: int
    deletions: int


class RecentMergesResponse(BaseModel):
    """Response for listing recently merged tasks."""

    merges: list[MergedTaskSummary]
    count: int


# --- Commit History Models ---


class CommitInfo(BaseModel):
    """Information about a single git commit."""

    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    date: str
    repo_name: str
    files_changed: int
    insertions: int
    deletions: int


class RecentCommitsResponse(BaseModel):
    """Response for recent commits."""

    commits: list[CommitInfo]
    count: int


# --- Snapshot Models ---


class SnapshotInfo(BaseModel):
    """Information about a pre-merge snapshot."""

    task_id: str
    task_title: str
    sha: str
    short_sha: str
    created_at: str
    project_id: str
    repo_name: str
    is_current: bool
    commits_ahead: int


class SnapshotsResponse(BaseModel):
    """Response for listing snapshots."""

    snapshots: list[SnapshotInfo]
    count: int


class ProjectDashboardResponse(BaseModel):
    """Combined dashboard data for a single project."""

    checkpoints: list[CheckpointInfo]
    branches: list[BranchInfo]
    recent_merges: list[MergedTaskSummary]
    recent_commits: list[CommitInfo]
    snapshots: list[SnapshotInfo]
    conflicts: list[ConflictInfo]
