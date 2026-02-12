"""Database queries for autonomous execution metrics."""

from datetime import datetime
# TYPE_CHECKING imported below

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg import Cursor

from .autonomous_models import GraduationProgress, IterationMetrics


def get_task_counts(
    cur: "Cursor[Any]", project_id: str, task_types: list[str]
) -> dict[str, int]:
    """Get counts of tasks by status."""
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'pending' AND labels && %s) as pending,
            COUNT(*) FILTER (WHERE status = 'running') as in_progress,
            COUNT(*) FILTER (WHERE status = 'ai_reviewing') as pending_review
        FROM tasks WHERE project_id = %s
        """,
        (task_types, project_id),
    )
    result = cur.fetchone()
    return {
        "pending_tasks": int(result[0]) if result and result[0] else 0,
        "in_progress": int(result[1]) if result and result[1] else 0,
        "pending_review": int(result[2]) if result and result[2] else 0,
    }


def get_recent_completion_counts(
    cur: "Cursor[Any]", project_id: str, last_24h: datetime
) -> dict[str, int]:
    """Get counts of completed and failed tasks in last 24h."""
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'completed' AND completed_at >= %s) as completed,
            COUNT(*) FILTER (WHERE status = 'failed' AND created_at >= %s) as failed
        FROM tasks WHERE project_id = %s
        """,
        (last_24h, last_24h, project_id),
    )
    result = cur.fetchone()
    return {
        "completed_24h": int(result[0]) if result and result[0] else 0,
        "failed_24h": int(result[1]) if result and result[1] else 0,
    }


def get_approval_metrics(
    cur: "Cursor[Any]", project_id: str, last_7d: datetime
) -> dict[str, Any]:
    """Calculate approval rate from review_result (last 7 days)."""
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

    return {
        "approval_rate": approval_rate,
        "total_reviewed": total_reviewed,
    }


def get_iteration_metrics_data(
    cur: "Cursor[Any]", project_id: str, last_7d: datetime
) -> IterationMetrics:
    """Calculate iteration metrics from review_result (last 7 days)."""
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
    first_try_rate = (
        (first_try_count / total_completed * 100) if total_completed > 0 else 0.0
    )

    return IterationMetrics(
        avg_iterations_to_success=round(avg_iterations, 2),
        exhausted_count=exhausted_count,
        consult_count=consult_count,
        handoff_count=handoff_count,
        first_try_success_rate=round(first_try_rate, 1),
    )


def calculate_graduation_progress(
    total_reviewed: int, approval_rate: float
) -> GraduationProgress:
    """Calculate graduation progress (simple heuristic: need 10 tasks at >80% approval)."""
    tasks_until_graduation = max(0, 10 - total_reviewed)

    return GraduationProgress(
        tasks_until_graduation=tasks_until_graduation,
        current_approval_rate=round(approval_rate, 1),
    )
