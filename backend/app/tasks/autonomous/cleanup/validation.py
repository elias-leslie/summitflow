"""Post-merge validation and auto-rollback operations."""

from __future__ import annotations

import subprocess
from typing import Literal, TypedDict

from app.storage import tasks as task_store
from app.storage.agent_configs_quality import build_dt_command

from ....logging_config import get_logger
from ..exec_modules.quality_utils import find_dev_tools
from .git_operations import revert_merge_commit

logger = get_logger(__name__)


class PostMergeValidationResult(TypedDict):
    """Outcome of post-merge validation."""

    status: Literal["passed", "failed", "timed_out", "skipped", "error"]
    passed: bool
    should_rollback: bool
    detail: str | None


def _log_validation_failure(task_id: str, output: str) -> None:
    """Log a post-merge validation failure with truncated output."""
    from app.storage import log_task_event

    log_task_event(task_id, f"Post-merge validation: FAILED\n{output}")
    logger.warning(
        "Post-merge validation failed",
        extra={"task_id": task_id, "output": output[:200]},
    )


def _resolve_dt_command(project_id: str) -> list[str] | None:
    """Return the configured dt command for post-merge validation."""
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return None
    return build_dt_command(dt_cmd, project_id)


def _log_validation_skip(task_id: str, reason: str) -> None:
    """Log a validation skip caused by missing local tooling."""
    from app.storage import log_task_event

    log_task_event(task_id, f"Post-merge validation: SKIPPED - {reason}")
    logger.warning(
        "Post-merge validation skipped",
        extra={"task_id": task_id, "reason": reason},
    )


def _run_dt_quick(
    project_root: str,
    task_id: str,
    project_id: str,
) -> PostMergeValidationResult:
    """Run configured dt validation and classify the outcome."""
    from app.storage import log_task_event

    cmd = _resolve_dt_command(project_id)
    if not cmd:
        _log_validation_skip(task_id, "dt not available")
        return {
            "status": "skipped",
            "passed": True,
            "should_rollback": False,
            "detail": "dt not available",
        }

    result = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode == 0:
        log_task_event(task_id, "Post-merge validation: PASSED")
        logger.info("Post-merge validation passed", extra={"task_id": task_id})
        return {
            "status": "passed",
            "passed": True,
            "should_rollback": False,
            "detail": None,
        }

    output = (result.stdout + result.stderr)[-500:]
    _log_validation_failure(task_id, output)
    return {
        "status": "failed",
        "passed": False,
        "should_rollback": True,
        "detail": output,
    }


def run_post_merge_validation(
    task_id: str,
    project_root: str,
    project_id: str,
) -> PostMergeValidationResult:
    """Run quality checks on the merged main branch.

    Runs the configured dt quality gate on the project after merge.
    Logs results to task events.

    Args:
        task_id: Task ID for logging
        project_root: Path to project root
        project_id: Project ID

    Returns:
        Structured validation outcome.
    """
    from app.storage import log_task_event

    try:
        return _run_dt_quick(project_root, task_id, project_id)
    except subprocess.TimeoutExpired:
        log_task_event(task_id, "Post-merge validation: TIMEOUT (120s)")
        logger.warning("Post-merge validation timed out", extra={"task_id": task_id})
        return {
            "status": "timed_out",
            "passed": False,
            "should_rollback": False,
            "detail": "validation timed out after 120s",
        }
    except FileNotFoundError as e:
        _log_validation_skip(task_id, f"validation tool missing ({e})")
        return {
            "status": "skipped",
            "passed": True,
            "should_rollback": False,
            "detail": f"validation tool missing ({e})",
        }
    except Exception as e:
        log_task_event(task_id, f"Post-merge validation: ERROR - {e}")
        logger.warning(
            "Post-merge validation error",
            extra={"task_id": task_id, "error": str(e)},
        )
        return {
            "status": "error",
            "passed": False,
            "should_rollback": False,
            "detail": str(e),
        }


def _apply_rollback_side_effects(
    task_id: str,
    project_id: str,
    task_branch: str,
) -> None:
    """Create fix task, update status, and save learning after a successful revert."""
    from app.storage import log_task_event

    log_task_event(
        task_id,
        f"Auto-rollback: Reverted merge of {task_branch} due to regression",
    )
    logger.info(
        "Auto-rollback succeeded",
        extra={"task_id": task_id, "task_branch": task_branch},
    )
    create_regression_fix_task(task_id, project_id, task_branch)
    task = task_store.get_task(task_id) or {}
    if task.get("status") == "completed":
        task_store.update_task_status(task_id, "failed", validate_transition=False)
    else:
        task_store.update_task_status(task_id, "failed")
    save_rollback_learning(task_id, project_id, task_branch)


def auto_rollback(
    task_id: str,
    project_root: str,
    project_id: str,
    task_branch: str,
) -> bool:
    """Auto-revert a merge commit when post-merge validation fails.

    Reverts the most recent merge commit (HEAD), creates a regression fix task,
    and stores the rollback pattern as a memory episode.

    Args:
        task_id: Source task ID that caused the regression
        project_root: Path to project root
        project_id: Project ID
        task_branch: The branch that was merged

    Returns:
        True if rollback succeeded, False otherwise
    """
    from app.storage import log_task_event

    try:
        if not revert_merge_commit(task_id, project_root):
            return False

        _apply_rollback_side_effects(task_id, project_id, task_branch)
        return True

    except subprocess.TimeoutExpired:
        log_task_event(task_id, "Auto-rollback: git revert timed out")
        return False
    except Exception as e:
        log_task_event(task_id, f"Auto-rollback ERROR: {e}")
        logger.error(
            "Auto-rollback error",
            extra={"task_id": task_id, "error": str(e)},
        )
        return False


def create_regression_fix_task(
    task_id: str,
    project_id: str,
    task_branch: str,
) -> None:
    """Create a regression fix task after rollback.

    Args:
        task_id: Source task ID that caused the regression
        project_id: Project ID
        task_branch: Branch that was rolled back
    """
    from app.storage.tasks.core import create_task

    try:
        create_task(
            project_id=project_id,
            title=f"Fix regression from {task_id}",
            description=(
                f"Auto-rollback triggered: merge of task {task_id} "
                f"(branch {task_branch}) caused post-merge validation failure. "
                f"The merge has been reverted. Fix the issues and re-merge."
            ),
            task_type="regression",
            priority=1,
            parent_task_id=task_id,
            autonomous=True,
        )
    except Exception as e:
        logger.warning(
            "Failed to create regression fix task",
            extra={"task_id": task_id, "error": str(e)},
        )


def save_rollback_learning(
    task_id: str,
    project_id: str,
    task_branch: str,
) -> None:
    """Save rollback pattern to memory system.

    Args:
        task_id: Source task ID that was rolled back
        project_id: Project ID
        task_branch: Branch that was rolled back
    """
    try:
        from app.services.agent_hub_client import get_sync_client

        client = get_sync_client()
        client.save_learning(
            f"Merge of task {task_id} (branch {task_branch}) was auto-reverted "
            f"due to post-merge validation failure. Ensure all quality checks "
            f"pass before merging.",
            injection_tier="guardrail",
            confidence=85,
            context=f"task:{task_id} rollback",
            scope="project",
            scope_id=project_id,
        )
    except Exception:
        logger.debug("Failed to save rollback learning to memory system", exc_info=True)
