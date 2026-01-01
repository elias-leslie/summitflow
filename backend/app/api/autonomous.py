"""Autonomous execution settings and status API."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.worktree_manager import WorktreeError, get_worktree_manager
from ..storage.agent_configs import get_agent_config, update_agent_config
from ..storage.connection import get_connection

# Default repository path for worktree operations
DEFAULT_REPO_PATH = Path("/home/kasadis/summitflow")

router = APIRouter()


# --- Settings Models ---


class AutonomousSettings(BaseModel):
    """Autonomous execution settings for a project."""

    enabled: bool = Field(default=False, description="Master switch for autonomous execution")
    frequency_minutes: int = Field(
        default=30, ge=5, le=1440, description="How often to check for work (5-1440 min)"
    )
    auto_merge_tiers: list[int] = Field(
        default=[1], description="Tiers that can auto-merge without human review"
    )
    task_types: list[str] = Field(
        default=["auto-generated"],
        description="Task labels eligible for autonomous execution",
    )


class AutonomousSettingsUpdate(BaseModel):
    """Request model for updating autonomous settings."""

    enabled: bool | None = None
    frequency_minutes: int | None = Field(default=None, ge=5, le=1440)
    auto_merge_tiers: list[int] | None = None
    task_types: list[str] | None = None


# --- Status Models ---


class IterationMetrics(BaseModel):
    """Metrics about iteration behavior."""

    avg_iterations_to_success: float = Field(
        default=0.0, description="Average iterations for completed tasks (7 days)"
    )
    exhausted_count: int = Field(
        default=0, description="Tasks that hit max_iterations without success (7 days)"
    )
    consult_count: int = Field(
        default=0, description="Times alternate model was consulted (7 days)"
    )
    handoff_count: int = Field(default=0, description="Times full handoff occurred (7 days)")
    first_try_success_rate: float = Field(
        default=0.0, description="Percentage of tasks that passed on iteration 1"
    )


class GraduationProgress(BaseModel):
    """Progress toward graduating to higher autonomy."""

    tasks_until_graduation: int = Field(default=10, description="Tasks remaining before review")
    current_approval_rate: float = Field(default=0.0, description="Current review approval rate")


class AutonomousStatus(BaseModel):
    """Current autonomous execution status."""

    enabled: bool
    last_run: datetime | None = None
    pending_tasks: int = Field(default=0, description="Auto-generated pending tasks")
    in_progress: int = Field(default=0, description="Currently running tasks")
    pending_review: int = Field(default=0, description="Tasks awaiting review")
    completed_24h: int = Field(default=0, description="Completed in last 24 hours")
    failed_24h: int = Field(default=0, description="Failed in last 24 hours")
    approval_rate: float = Field(default=0.0, description="Review approval rate (7 days)")
    auto_merge_tiers: list[int] = Field(default=[1], description="Tiers eligible for auto-merge")
    graduation: GraduationProgress = Field(default_factory=GraduationProgress)
    iteration_metrics: IterationMetrics = Field(default_factory=IterationMetrics)


# --- Helper Functions ---


def _get_autonomous_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous settings from agent config."""
    config = get_agent_config(project_id)

    # Extract autonomous-specific settings or use defaults
    # Cast values since AgentConfig has partial TypedDict keys
    from typing import cast

    enabled = bool(config.get("autonomous_enabled", False))
    freq_raw = config.get("autonomous_frequency_minutes", 30)
    frequency_minutes = int(cast(int, freq_raw) if freq_raw else 30)
    auto_merge_tiers_raw = config.get("autonomous_auto_merge_tiers")
    auto_merge_tiers = list(cast(list[int], auto_merge_tiers_raw)) if auto_merge_tiers_raw else [1]
    task_types_raw = config.get("autonomous_task_types")
    task_types = list(cast(list[str], task_types_raw)) if task_types_raw else ["auto-generated"]

    return AutonomousSettings(
        enabled=enabled,
        frequency_minutes=frequency_minutes,
        auto_merge_tiers=auto_merge_tiers,
        task_types=task_types,
    )


def _update_autonomous_settings(
    project_id: str, settings: AutonomousSettingsUpdate
) -> AutonomousSettings:
    """Update autonomous settings in agent config."""
    updates: dict[str, Any] = {}

    if settings.enabled is not None:
        updates["autonomous_enabled"] = settings.enabled
    if settings.frequency_minutes is not None:
        updates["autonomous_frequency_minutes"] = settings.frequency_minutes
    if settings.auto_merge_tiers is not None:
        updates["autonomous_auto_merge_tiers"] = settings.auto_merge_tiers
    if settings.task_types is not None:
        updates["autonomous_task_types"] = settings.task_types

    if updates:
        update_agent_config(project_id, updates)  # type: ignore[arg-type]

    return _get_autonomous_settings(project_id)


# --- API Endpoints ---


@router.get("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def get_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous execution settings for a project."""
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return _get_autonomous_settings(project_id)


@router.patch("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def update_settings(project_id: str, update: AutonomousSettingsUpdate) -> AutonomousSettings:
    """Update autonomous execution settings for a project."""
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # Validate auto_merge_tiers
    if update.auto_merge_tiers is not None:
        for tier in update.auto_merge_tiers:
            if tier < 1 or tier > 4:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid tier {tier}. Tiers must be 1-4.",
                )

    return _update_autonomous_settings(project_id, update)


@router.get("/{project_id}/autonomous/status", response_model=AutonomousStatus)
async def get_status(project_id: str) -> AutonomousStatus:
    """Get autonomous execution status and metrics for a project."""
    # Verify project exists and get settings
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    settings = _get_autonomous_settings(project_id)
    now = datetime.now(UTC)
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    with get_connection() as conn, conn.cursor() as cur:
        # Count pending auto-generated tasks
        cur.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE project_id = %s
              AND status = 'pending'
              AND labels && %s
            """,
            (project_id, settings.task_types),
        )
        result = cur.fetchone()
        pending_tasks = int(result[0]) if result and result[0] else 0

        # Count in-progress tasks
        cur.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE project_id = %s
              AND status = 'running'
            """,
            (project_id,),
        )
        result = cur.fetchone()
        in_progress = int(result[0]) if result and result[0] else 0

        # Count pending_review tasks
        cur.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE project_id = %s
              AND status = 'pending_review'
            """,
            (project_id,),
        )
        result = cur.fetchone()
        pending_review = int(result[0]) if result and result[0] else 0

        # Count completed in last 24h (use completed_at)
        cur.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE project_id = %s
              AND status = 'completed'
              AND completed_at >= %s
            """,
            (project_id, last_24h),
        )
        result = cur.fetchone()
        completed_24h = int(result[0]) if result and result[0] else 0

        # Count failed in last 24h (use created_at as fallback - tasks don't have failed_at)
        cur.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE project_id = %s
              AND status = 'failed'
              AND created_at >= %s
            """,
            (project_id, last_24h),
        )
        result = cur.fetchone()
        failed_24h = int(result[0]) if result and result[0] else 0

        # Calculate approval rate from review_result (last 7 days)
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE review_result->>'verdict' = 'APPROVE') as approved,
                COUNT(*) FILTER (WHERE review_result IS NOT NULL) as total
            FROM tasks
            WHERE project_id = %s
              AND (completed_at >= %s OR created_at >= %s)
            """,
            (project_id, last_7d, last_7d),
        )
        result = cur.fetchone()
        approved = int(result[0]) if result and result[0] else 0
        total_reviewed = int(result[1]) if result and result[1] else 0
        approval_rate = (approved / total_reviewed * 100) if total_reviewed > 0 else 0.0

        # Calculate iteration metrics from review_result (last 7 days)
        # Note: iteration counts stored in review_result.iterations
        cur.execute(
            """
            SELECT
                AVG((review_result->>'iterations')::int)
                    FILTER (WHERE status = 'completed' AND review_result->>'iterations' IS NOT NULL),
                COUNT(*) FILTER (WHERE review_result->>'reason' = 'exhausted'),
                COUNT(*) FILTER (WHERE review_result->>'consulted' = 'true'),
                COUNT(*) FILTER (WHERE review_result->>'handoff' = 'true'),
                COUNT(*) FILTER (WHERE (review_result->>'iterations')::int = 1 AND status = 'completed'),
                COUNT(*) FILTER (WHERE status = 'completed' AND review_result->>'iterations' IS NOT NULL)
            FROM tasks
            WHERE project_id = %s
              AND (completed_at >= %s OR created_at >= %s)
            """,
            (project_id, last_7d, last_7d),
        )
        result = cur.fetchone()
        avg_iterations = float(result[0]) if result and result[0] else 0.0
        exhausted_count = int(result[1]) if result and result[1] else 0
        consult_count = int(result[2]) if result and result[2] else 0
        handoff_count = int(result[3]) if result and result[3] else 0
        first_try_count = int(result[4]) if result and result[4] else 0
        total_completed = int(result[5]) if result and result[5] else 0
        first_try_rate = (first_try_count / total_completed * 100) if total_completed > 0 else 0.0

    # Graduation progress (simple heuristic: need 10 tasks at >80% approval)
    tasks_until_graduation = max(0, 10 - total_reviewed)

    return AutonomousStatus(
        enabled=settings.enabled,
        last_run=None,  # Could track this in a separate table if needed
        pending_tasks=pending_tasks,
        in_progress=in_progress,
        pending_review=pending_review,
        completed_24h=completed_24h,
        failed_24h=failed_24h,
        approval_rate=round(approval_rate, 1),
        auto_merge_tiers=settings.auto_merge_tiers,
        graduation=GraduationProgress(
            tasks_until_graduation=tasks_until_graduation,
            current_approval_rate=round(approval_rate, 1),
        ),
        iteration_metrics=IterationMetrics(
            avg_iterations_to_success=round(avg_iterations, 2),
            exhausted_count=exhausted_count,
            consult_count=consult_count,
            handoff_count=handoff_count,
            first_try_success_rate=round(first_try_rate, 1),
        ),
    )


# --- Worktree Models ---


class WorktreeInfo(BaseModel):
    """Information about an active worktree."""

    task_id: str
    project_id: str
    path: str
    branch: str
    base_branch: str
    commit_count: int = 0
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0


class WorktreeList(BaseModel):
    """List of active worktrees."""

    worktrees: list[WorktreeInfo]
    count: int


class CleanupResult(BaseModel):
    """Result of worktree cleanup operation."""

    removed_count: int
    removed_by_age: int = 0
    removed_by_status: int = 0


class MergeResult(BaseModel):
    """Result of worktree merge operation."""

    success: bool
    task_id: str
    message: str


# --- Worktree API Endpoints ---


@router.get("/{project_id}/autonomous/worktrees", response_model=WorktreeList)
async def list_worktrees(project_id: str) -> WorktreeList:
    """List all active worktrees for a project."""
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    manager = get_worktree_manager(DEFAULT_REPO_PATH)
    active = manager.list_active_worktrees(project_id)

    worktrees = [
        WorktreeInfo(
            task_id=w.task_id,
            project_id=w.project_id,
            path=str(w.path),
            branch=w.branch,
            base_branch=w.base_branch,
            commit_count=w.commit_count,
            files_changed=w.files_changed,
            additions=w.additions,
            deletions=w.deletions,
        )
        for w in active
    ]

    return WorktreeList(worktrees=worktrees, count=len(worktrees))


@router.post("/{project_id}/autonomous/worktrees/cleanup", response_model=CleanupResult)
async def cleanup_worktrees(project_id: str, max_age_hours: int = 24) -> CleanupResult:
    """Manually trigger worktree cleanup for a project.

    Args:
        project_id: Project ID
        max_age_hours: Maximum age in hours before cleanup (default 24)
    """
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    manager = get_worktree_manager(DEFAULT_REPO_PATH)

    # Cleanup by age
    removed_by_age = manager.cleanup_stale_worktrees(max_age_hours)

    # Cleanup by task status (only for this project)
    from ..storage import tasks as task_store

    removed_by_status = 0
    active_worktrees = manager.list_active_worktrees(project_id)

    for worktree in active_worktrees:
        task = task_store.get_task(worktree.task_id)
        if not task or task.get("status") not in ("running", "pending_review"):
            try:
                manager.remove_worktree(project_id, worktree.task_id)
                removed_by_status += 1
            except Exception:
                pass  # Best effort

    return CleanupResult(
        removed_count=removed_by_age + removed_by_status,
        removed_by_age=removed_by_age,
        removed_by_status=removed_by_status,
    )


@router.post("/{project_id}/autonomous/worktrees/{task_id}/merge", response_model=MergeResult)
async def merge_worktree(project_id: str, task_id: str, delete_after: bool = True) -> MergeResult:
    """Manually merge a task's worktree to the base branch.

    Args:
        project_id: Project ID
        task_id: Task ID whose worktree to merge
        delete_after: Whether to remove worktree after merge (default True)
    """
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    manager = get_worktree_manager(DEFAULT_REPO_PATH)

    # Check worktree exists
    if not manager.worktree_exists(project_id, task_id):
        raise HTTPException(
            status_code=404,
            detail=f"No worktree found for task {task_id}",
        )

    try:
        success = await manager.merge_worktree(project_id, task_id, delete_after=delete_after)

        if success:
            return MergeResult(
                success=True,
                task_id=task_id,
                message=f"Successfully merged worktree for task {task_id}",
            )
        else:
            return MergeResult(
                success=False,
                task_id=task_id,
                message="Merge failed - likely a conflict. Worktree preserved.",
            )
    except WorktreeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/{project_id}/autonomous/worktrees/{task_id}", response_model=MergeResult)
async def remove_worktree(project_id: str, task_id: str, delete_branch: bool = True) -> MergeResult:
    """Remove a task's worktree without merging.

    Args:
        project_id: Project ID
        task_id: Task ID whose worktree to remove
        delete_branch: Whether to also delete the branch (default True)
    """
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    manager = get_worktree_manager(DEFAULT_REPO_PATH)

    try:
        manager.remove_worktree(project_id, task_id, delete_branch=delete_branch)
        return MergeResult(
            success=True,
            task_id=task_id,
            message=f"Removed worktree for task {task_id}",
        )
    except WorktreeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
