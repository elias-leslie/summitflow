"""Celery tasks for orchestrator execution.

Tasks:
- execute_orchestrator_task: Execute autonomous orchestration on a task
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.orchestrator import OrchestrationResult, OrchestratorService
from ..storage import tasks

logger = get_logger(__name__)


def _result_to_dict(result: OrchestrationResult) -> dict[str, Any]:
    """Convert OrchestrationResult to serializable dict."""
    return {
        "task_id": result.task_id,
        "success": result.success,
        "state": result.state.value,
        "error": result.error,
        "total_iterations": result.total_iterations,
        "worktree_reverted": result.worktree_reverted,
        "merge_sha": result.merge_sha,
        "subtask_results": [
            {
                "subtask_id": sr.subtask_id,
                "success": sr.success,
                "error": sr.error,
                "iterations": sr.iterations,
                "model_used": sr.model_used,
                "commit_sha": sr.commit_sha,
            }
            for sr in result.subtask_results
        ],
    }


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.execute_orchestrator",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=3600,  # 1 hour soft limit
    time_limit=3900,  # 1 hour 5 minutes hard limit
)
def execute_orchestrator_task(
    self: Any,
    project_id: str,
    task_id: str,
    worker_id: str | None = None,
    lock_duration_minutes: int = 60,
) -> dict[str, Any]:
    """Execute orchestrator on a specific task.

    Runs the Sonnet coordinator pattern with Flash workers.

    Args:
        self: Celery task instance
        project_id: Project containing the task
        task_id: The task ID to execute
        worker_id: Optional worker ID for claiming
        lock_duration_minutes: How long to hold task lock

    Returns:
        OrchestrationResult as serializable dict
    """
    logger.info(
        "orchestrator_task_started",
        project_id=project_id,
        task_id=task_id,
        worker_id=worker_id,
    )

    # Verify task exists
    task = tasks.get_task(task_id)
    if not task:
        logger.error("task_not_found", task_id=task_id)
        return {"status": "error", "error": f"Task not found: {task_id}"}

    # Create orchestrator service
    orchestrator = OrchestratorService(
        project_id=project_id,
        ws_task_id=task_id,
    )

    # Run async coordination in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            orchestrator.coordinate(
                task_id=task_id,
                worker_id=worker_id,
                lock_duration_minutes=lock_duration_minutes,
            )
        )

        result_dict = _result_to_dict(result)
        logger.info(
            "orchestrator_task_completed",
            task_id=task_id,
            success=result.success,
            state=result.state.value,
        )
        return result_dict

    except Exception as e:
        logger.error("orchestrator_task_failed", task_id=task_id, error=str(e))
        tasks.update_task_status(task_id, "failed", error_message=str(e))
        return {"status": "error", "error": str(e)}

    finally:
        loop.close()
