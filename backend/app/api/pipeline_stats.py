"""Pipeline statistics computation module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

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


def _compute_self_healing(results: list[dict[str, Any]]) -> SelfHealing:
    """Compute self-healing metrics from verification results."""
    total = len(results)
    if total == 0:
        return SelfHealing(
            first_attempt_pass_rate=0.0, avg_self_fix_attempts=0.0,
            supervisor_escalation_rate=0.0, model_escalation_count=0
        )
    first_pass = sum(1 for vr in results if vr.get("execution_clean", False))
    total_fixes = sum(vr.get("total_self_fix_attempts", 0) or vr.get("self_fix_attempts", 0) for vr in results)
    supervisor_esc = sum(
        1 for vr in results if (vr.get("total_supervisor_attempts", 0) or vr.get("supervisor_guided_attempts", 0)) > 0
    )
    model_esc = sum(1 for vr in results if vr.get("model_escalated", False) or vr.get("tier_upgraded", False))
    return SelfHealing(
        first_attempt_pass_rate=round(first_pass / total, 2),
        avg_self_fix_attempts=round(total_fixes / total, 2),
        supervisor_escalation_rate=round(supervisor_esc / total, 2),
        model_escalation_count=model_esc,
    )


def _compute_verification(results: list[dict[str, Any]]) -> Verification:
    """Compute verification metrics from step results."""
    total_steps, passed_steps, total_retries = 0, 0, 0
    for vr in results:
        step_results = vr.get("step_results", [])
        if not isinstance(step_results, list):
            continue
        for step in step_results:
            if not isinstance(step, dict):
                continue
            total_steps += 1
            if step.get("passed", False):
                passed_steps += 1
            retries = step.get("retry_count", 0) or step.get("attempts", 0) - 1
            total_retries += max(0, retries)
    if total_steps == 0:
        return Verification(step_pass_rate=0.0, avg_retries_per_step=0.0)
    return Verification(
        step_pass_rate=round(passed_steps / total_steps, 2),
        avg_retries_per_step=round(total_retries / total_steps, 2),
    )


def _compute_partial_merge(results: list[dict[str, Any]]) -> PartialMerge:
    """Compute partial merge metrics from verification results."""
    total = len(results)
    if total == 0:
        return PartialMerge(full_completion_rate=0.0, partial_completion_rate=0.0, total_failure_rate=0.0)
    full = sum(1 for vr in results if vr.get("execution_clean", False) and not vr.get("partial_merge", False))
    partial = sum(1 for vr in results if vr.get("partial_merge", False))
    failures = sum(1 for vr in results if vr.get("passed_count", 0) == 0 and vr.get("subtask_count", 0) > 0)
    return PartialMerge(
        full_completion_rate=round(full / total, 2),
        partial_completion_rate=round(partial / total, 2),
        total_failure_rate=round(failures / total, 2),
    )


def compute_pipeline_stats(project_id: str) -> PipelineStatsResponse:
    """Compute pipeline statistics for a project (sync version for thread pool)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, COUNT(*) FROM tasks WHERE project_id = %s GROUP BY status", (project_id,))
        status_counts = {row[0]: row[1] for row in cur.fetchall()}
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = datetime.now(UTC) - timedelta(days=7)
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE project_id = %s AND status = 'completed' AND completed_at >= %s",
            (project_id, today),
        )
        completed_today = (cur.fetchone() or (0,))[0]
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE project_id = %s AND status = 'completed' AND completed_at >= %s",
            (project_id, week_ago),
        )
        completed_week = (cur.fetchone() or (0,))[0]
        cur.execute(
            """SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) / 3600.0)
            FROM tasks WHERE project_id = %s AND status = 'completed'
            AND started_at IS NOT NULL AND completed_at IS NOT NULL""",
            (project_id,),
        )
        result = cur.fetchone()
        avg_hours = round(result[0], 2) if result and result[0] is not None else 0.0
        cur.execute(
            """SELECT verification_result FROM tasks WHERE project_id = %s
            AND status IN ('completed', 'failed', 'abandoned') AND verification_result IS NOT NULL""",
            (project_id,),
        )
        verification_results = [row[0] for row in cur.fetchall() if isinstance(row[0], dict)]
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE project_id = %s AND autonomous = true AND status = 'running'",
            (project_id,),
        )
        running = (cur.fetchone() or (0,))[0]
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE project_id = %s AND autonomous = true AND status = 'queue'",
            (project_id,),
        )
        queue = (cur.fetchone() or (0,))[0]
        cur.execute(
            """SELECT created_at FROM tasks WHERE project_id = %s AND autonomous = true AND status = 'queue'
            ORDER BY priority ASC, created_at ASC LIMIT 1""",
            (project_id,),
        )
        next_task = cur.fetchone()
        next_scheduled = next_task[0].isoformat() if next_task else None
    settings = get_autonomous_settings(project_id)
    return PipelineStatsResponse(
        task_distribution=TaskDistribution(
            pending=status_counts.get("pending", 0), queue=status_counts.get("queue", 0),
            running=status_counts.get("running", 0), ai_reviewing=status_counts.get("ai_reviewing", 0),
            completed=status_counts.get("completed", 0), blocked=status_counts.get("blocked", 0),
            failed=status_counts.get("failed", 0), cancelled=status_counts.get("cancelled", 0),
            abandoned=status_counts.get("abandoned", 0),
        ),
        throughput=Throughput(
            completed_today=completed_today, completed_this_week=completed_week, avg_completion_hours=avg_hours
        ),
        self_healing=_compute_self_healing(verification_results),
        verification=_compute_verification(verification_results),
        partial_merge=_compute_partial_merge(verification_results),
        autonomous=Autonomous(
            running_count=running, max_concurrent=settings.max_concurrent,
            queue_depth=queue, next_scheduled=next_scheduled
        ),
    )
