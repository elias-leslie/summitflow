"""Pipeline metrics API endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException

from ..services.health_cache import HealthCache
from ..storage.connection import get_connection
from .autonomous_service import get_autonomous_settings
from .pipeline_models import (
    Autonomous,
    PartialMerge,
    PipelineStatsResponse,
    SelfHealing,
    TaskDistribution,
    Throughput,
    Verification,
)

router = APIRouter()

# Cache pipeline stats for 30 seconds
_pipeline_stats_cache: HealthCache[PipelineStatsResponse] | None = None


def _get_pipeline_stats_cache() -> HealthCache[PipelineStatsResponse]:
    """Get the singleton pipeline stats cache instance."""
    global _pipeline_stats_cache
    if _pipeline_stats_cache is None:
        _pipeline_stats_cache = HealthCache[PipelineStatsResponse]()
    return _pipeline_stats_cache


def _verify_project_exists(project_id: str) -> None:
    """Verify that a project exists, raising 404 if not."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


async def _fetch_pipeline_stats(project_id: str) -> PipelineStatsResponse:
    """
    Internal function to fetch fresh pipeline statistics.

    This function is separated to enable caching. It computes all metrics
    from the tasks table and autonomous settings.
    """
    import asyncio

    # Run database queries in thread pool
    return await asyncio.to_thread(_compute_pipeline_stats, project_id)


def _compute_pipeline_stats(project_id: str) -> PipelineStatsResponse:
    """Compute pipeline statistics for a project (sync version for thread pool)."""
    with get_connection() as conn, conn.cursor() as cur:
        # 1. Task distribution by status
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM tasks
            WHERE project_id = %s
            GROUP BY status
            """,
            (project_id,),
        )
        status_counts = {row[0]: row[1] for row in cur.fetchall()}

        # 2. Throughput metrics
        # Tasks completed today
        cur.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE project_id = %s
              AND status = 'completed'
              AND completed_at >= %s
            """,
            (project_id, datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)),
        )
        result = cur.fetchone()
        completed_today = result[0] if result else 0

        # Tasks completed this week (last 7 days)
        cur.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE project_id = %s
              AND status = 'completed'
              AND completed_at >= %s
            """,
            (project_id, datetime.now(UTC) - timedelta(days=7)),
        )
        result = cur.fetchone()
        completed_this_week = result[0] if result else 0

        # Average completion time (in hours)
        cur.execute(
            """
            SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) / 3600.0) as avg_hours
            FROM tasks
            WHERE project_id = %s
              AND status = 'completed'
              AND started_at IS NOT NULL
              AND completed_at IS NOT NULL
            """,
            (project_id,),
        )
        result = cur.fetchone()
        avg_completion_hours = round(result[0], 2) if result[0] is not None else 0.0

        # 3. Self-healing metrics (from verification_result JSONB)
        # Get all completed/failed tasks with verification results
        cur.execute(
            """
            SELECT verification_result
            FROM tasks
            WHERE project_id = %s
              AND status IN ('completed', 'failed', 'abandoned')
              AND verification_result IS NOT NULL
            """,
            (project_id,),
        )
        verification_results = [row[0] for row in cur.fetchall()]

        # Calculate self-healing metrics
        total_tasks = len(verification_results)
        first_attempt_pass = 0
        total_self_fix_attempts = 0
        supervisor_escalations = 0
        model_escalations = 0

        for vr in verification_results:
            if not isinstance(vr, dict):
                continue

            # Count first attempt passes (execution_clean = True means no retries needed)
            if vr.get("execution_clean", False):
                first_attempt_pass += 1

            # Sum self-fix attempts
            self_fix = vr.get("total_self_fix_attempts", 0) or vr.get("self_fix_attempts", 0)
            total_self_fix_attempts += self_fix

            # Count supervisor escalations
            supervisor = vr.get("total_supervisor_attempts", 0) or vr.get("supervisor_guided_attempts", 0)
            if supervisor > 0:
                supervisor_escalations += 1

            # Count model escalations (tier upgrades)
            if vr.get("model_escalated", False) or vr.get("tier_upgraded", False):
                model_escalations += 1

        first_attempt_pass_rate = (
            round(first_attempt_pass / total_tasks, 2) if total_tasks > 0 else 0.0
        )
        avg_self_fix_attempts = (
            round(total_self_fix_attempts / total_tasks, 2) if total_tasks > 0 else 0.0
        )
        supervisor_escalation_rate = (
            round(supervisor_escalations / total_tasks, 2) if total_tasks > 0 else 0.0
        )

        # 4. Verification metrics (step-level pass rates)
        # Parse step results from verification_result
        total_steps = 0
        passed_steps = 0
        total_retries = 0

        for vr in verification_results:
            if not isinstance(vr, dict):
                continue

            step_results = vr.get("step_results", [])
            if isinstance(step_results, list):
                for step in step_results:
                    if isinstance(step, dict):
                        total_steps += 1
                        if step.get("passed", False):
                            passed_steps += 1
                        # Count retries for this step
                        retries = step.get("retry_count", 0) or step.get("attempts", 0) - 1
                        total_retries += max(0, retries)

        step_pass_rate = round(passed_steps / total_steps, 2) if total_steps > 0 else 0.0
        avg_retries_per_step = round(total_retries / total_steps, 2) if total_steps > 0 else 0.0

        # 5. Partial merge metrics
        full_completions = 0
        partial_completions = 0
        total_failures = 0

        for vr in verification_results:
            if not isinstance(vr, dict):
                continue

            # Full completion: all subtasks passed
            if vr.get("execution_clean", False) and not vr.get("partial_merge", False):
                full_completions += 1
            # Partial completion: some subtasks passed
            elif vr.get("partial_merge", False):
                partial_completions += 1
            # Total failure: no subtasks passed
            elif vr.get("passed_count", 0) == 0 and vr.get("subtask_count", 0) > 0:
                total_failures += 1

        full_completion_rate = (
            round(full_completions / total_tasks, 2) if total_tasks > 0 else 0.0
        )
        partial_completion_rate = (
            round(partial_completions / total_tasks, 2) if total_tasks > 0 else 0.0
        )
        total_failure_rate = round(total_failures / total_tasks, 2) if total_tasks > 0 else 0.0

        # 6. Autonomous execution metrics
        # Count running autonomous tasks
        cur.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE project_id = %s
              AND autonomous = true
              AND status = 'running'
            """,
            (project_id,),
        )
        result = cur.fetchone()
        running_count = result[0] if result else 0

        # Count queued autonomous tasks
        cur.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE project_id = %s
              AND autonomous = true
              AND status = 'queue'
            """,
            (project_id,),
        )
        result = cur.fetchone()
        queue_depth = result[0] if result else 0

        # Get next scheduled task (earliest in queue)
        cur.execute(
            """
            SELECT created_at
            FROM tasks
            WHERE project_id = %s
              AND autonomous = true
              AND status = 'queue'
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
            """,
            (project_id,),
        )
        next_task = cur.fetchone()
        next_scheduled = next_task[0].isoformat() if next_task else None

    # Get autonomous settings for max_concurrent
    settings = get_autonomous_settings(project_id)
    max_concurrent = settings.max_concurrent

    return PipelineStatsResponse(
        task_distribution={
            "pending": status_counts.get("pending", 0),
            "queue": status_counts.get("queue", 0),
            "running": status_counts.get("running", 0),
            "ai_reviewing": status_counts.get("ai_reviewing", 0),
            "completed": status_counts.get("completed", 0),
            "blocked": status_counts.get("blocked", 0),
            "failed": status_counts.get("failed", 0),
            "cancelled": status_counts.get("cancelled", 0),
            "abandoned": status_counts.get("abandoned", 0),
        },
        throughput={
            "completed_today": completed_today,
            "completed_this_week": completed_this_week,
            "avg_completion_hours": avg_completion_hours,
        },
        self_healing={
            "first_attempt_pass_rate": first_attempt_pass_rate,
            "avg_self_fix_attempts": avg_self_fix_attempts,
            "supervisor_escalation_rate": supervisor_escalation_rate,
            "model_escalation_count": model_escalations,
        },
        verification={
            "step_pass_rate": step_pass_rate,
            "avg_retries_per_step": avg_retries_per_step,
        },
        partial_merge={
            "full_completion_rate": full_completion_rate,
            "partial_completion_rate": partial_completion_rate,
            "total_failure_rate": total_failure_rate,
        },
        autonomous={
            "running_count": running_count,
            "max_concurrent": max_concurrent,
            "queue_depth": queue_depth,
            "next_scheduled": next_scheduled,
        },
    )


@router.get("/pipeline/stats", response_model=PipelineStatsResponse)
async def get_pipeline_stats(project_id: str) -> PipelineStatsResponse:
    """
    Get pipeline health statistics for a project.

    Returns task distribution, throughput metrics, self-healing statistics,
    verification data, partial merge rates, and autonomous execution state.

    Uses caching with 30-second TTL for performance.

    Args:
        project_id: Project ID to get stats for

    Returns:
        Pipeline statistics including all metrics defined in PipelineStatsResponse
    """
    _verify_project_exists(project_id)

    # Use cache with 30-second TTL (similar to health endpoint pattern)
    cache = _get_pipeline_stats_cache()

    # Create a project-specific fetch function
    async def fetch_fn() -> PipelineStatsResponse:
        return await _fetch_pipeline_stats(project_id)

    result = await cache.get_or_refresh(fetch_fn)
    if result is None:
        raise HTTPException(status_code=503, detail="Pipeline stats unavailable")

    return result
