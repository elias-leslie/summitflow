"""Autonomous execution service layer."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ..storage.agent_configs import get_agent_config, update_agent_config
from ..storage.connection import get_connection
from .autonomous_models import (
    AutonomousSettings,
    AutonomousSettingsUpdate,
    AutonomousStatus,
    GraduationProgress,
    IterationMetrics,
)


def get_autonomous_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous settings from agent config."""
    config = get_agent_config(project_id)

    # Extract autonomous-specific settings or use defaults
    enabled = bool(config.get("autonomous_enabled", False))
    freq_raw = config.get("autonomous_frequency_minutes", 30)
    frequency_minutes = int(cast(int, freq_raw) if freq_raw else 30)
    auto_merge_tiers_raw = config.get("autonomous_auto_merge_tiers")
    auto_merge_tiers = list(cast(list[int], auto_merge_tiers_raw)) if auto_merge_tiers_raw else [1]
    task_types_raw = config.get("autonomous_task_types")
    task_types = list(cast(list[str], task_types_raw)) if task_types_raw else ["auto-generated"]

    # Schedule settings
    start_hour = int(config.get("autonomous_start_hour", 0))
    end_hour = int(config.get("autonomous_end_hour", 24))
    max_concurrent = int(config.get("autonomous_max_concurrent", 1))

    return AutonomousSettings(
        enabled=enabled,
        frequency_minutes=frequency_minutes,
        auto_merge_tiers=auto_merge_tiers,
        task_types=task_types,
        start_hour=start_hour,
        end_hour=end_hour,
        max_concurrent=max_concurrent,
    )


def update_autonomous_settings(
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
    # Schedule settings
    if settings.start_hour is not None:
        updates["autonomous_start_hour"] = settings.start_hour
    if settings.end_hour is not None:
        updates["autonomous_end_hour"] = settings.end_hour
    if settings.max_concurrent is not None:
        updates["autonomous_max_concurrent"] = settings.max_concurrent

    if updates:
        update_agent_config(project_id, updates)  # type: ignore[arg-type]

    return get_autonomous_settings(project_id)


def get_autonomous_status(project_id: str) -> AutonomousStatus:
    """Get autonomous execution status and metrics for a project."""
    settings = get_autonomous_settings(project_id)
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

        # Count ai_reviewing tasks (tasks awaiting review)
        cur.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE project_id = %s
              AND status = 'ai_reviewing'
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
