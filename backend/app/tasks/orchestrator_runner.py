"""Celery tasks for orchestrator execution.

Tasks:
- execute_orchestrator_task: Execute autonomous orchestration on a task
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from app.celery_app import celery_app
from app.logging_config import get_logger
from app.services.orchestrator import OrchestrationResult, OrchestratorService
from app.storage import tasks

logger = get_logger(__name__)


class PristineCheckError(Exception):
    """Raised when codebase is not in pristine state."""

    pass


def check_pristine_codebase(project_id: str) -> None:
    """Verify codebase passes quality gates before automated execution.

    Runs lint, types, and tests to ensure no pre-existing failures that would
    cause false breaking change detection.

    Args:
        project_id: Project to check

    Raises:
        PristineCheckError: If quality gates fail
    """
    from app.storage.projects import get_project_root_path

    root_path = get_project_root_path(project_id)
    if not root_path:
        raise PristineCheckError(f"Project {project_id} not found or has no root_path")

    repo_path = Path(root_path)
    dev_tools_script = repo_path / "scripts" / "dev-tools.sh"

    if not dev_tools_script.exists():
        logger.warning(
            "pristine_check_skipped",
            project_id=project_id,
            reason="dev-tools.sh not found",
        )
        return

    logger.info("pristine_check_started", project_id=project_id)

    try:
        result = subprocess.run(
            [str(dev_tools_script), "--check"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes max
        )

        if result.returncode != 0:
            # Extract failure details from output
            output = result.stdout + result.stderr
            logger.error(
                "pristine_check_failed",
                project_id=project_id,
                exit_code=result.returncode,
                output=output[:2000],
            )
            raise PristineCheckError(
                f"Codebase quality gates failed (exit code {result.returncode}). "
                f"Fix lint/type/test errors before running automated execution. "
                f"Run './scripts/dev-tools.sh --check' to see details."
            )

        logger.info("pristine_check_passed", project_id=project_id)

    except subprocess.TimeoutExpired as e:
        raise PristineCheckError(
            "Pristine check timed out after 10 minutes. "
            "Run './scripts/dev-tools.sh --check' manually to investigate."
        ) from e
    except FileNotFoundError as e:
        logger.warning(
            "pristine_check_skipped",
            project_id=project_id,
            reason=f"Script not executable: {e}",
        )
        return


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


@celery_app.task(  # type: ignore[untyped-decorator]
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

    # Verify codebase is pristine before automated execution
    try:
        check_pristine_codebase(project_id)
    except PristineCheckError as e:
        logger.error("pristine_check_failed", task_id=task_id, error=str(e))
        tasks.update_task_status(task_id, "blocked", error_message=str(e))
        return {
            "status": "blocked",
            "error": str(e),
            "task_id": task_id,
            "reason": "pristine_check_failed",
        }

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
