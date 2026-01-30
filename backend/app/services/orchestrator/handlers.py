"""Failure and interruption handlers for orchestrator.

Handles cleanup, PR creation, and review triggering.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ..worktree_manager import WorktreeManager
from .types import OrchestrationResult, SubtaskResult

logger = get_logger(__name__)


async def handle_failure(
    task_id: str,
    subtask_result: SubtaskResult,
    worktree_manager: WorktreeManager,
    project_id: str,
    send_log: object,
) -> bool:
    """Handle subtask failure by reverting worktree.

    Per decision d5: Self-heal 3 iterations, then auto-revert worktree.

    Args:
        task_id: Task ID
        subtask_result: Failed subtask result
        worktree_manager: WorktreeManager instance
        project_id: Project ID
        send_log: Async function to send log messages

    Returns:
        True if worktree was reverted successfully
    """
    async def _log(level: str, message: str) -> None:
        if callable(send_log):
            await send_log(level, message, "orchestrator")  
    await _log("warning", f"Reverting worktree after failure: {subtask_result.error}")

    try:
        worktree_manager.remove_worktree(project_id, task_id, delete_branch=True)

        task_store.update_task_status(
            task_id,
            "failed",
            error_message=subtask_result.error,
        )

        logger.info("worktree_reverted_on_failure", task_id=task_id)
        await _log("info", "Worktree reverted successfully")
        return True

    except Exception as e:
        logger.error("worktree_revert_failed", task_id=task_id, error=str(e))
        await _log("error", f"Failed to revert worktree: {e}")
        return False


async def handle_interruption(
    task_id: str,
    result: OrchestrationResult,
    chat_messages: list[dict[str, object]],
    current_worktree_path: Path | None,
    worktree_manager: WorktreeManager,
    project_id: str,
    send_log: object,
) -> None:
    """Handle user interruption gracefully.

    Per decision d2 and d6:
    - Store chat context for resume
    - Commit partial work
    - Update task status to paused

    Args:
        task_id: Task ID
        result: Current orchestration result
        chat_messages: Chat messages to preserve
        current_worktree_path: Current worktree path
        worktree_manager: WorktreeManager instance
        project_id: Project ID
        send_log: Async function to send log messages
    """
    async def _log(level: str, message: str) -> None:
        if callable(send_log):
            await send_log(level, message, "orchestrator")  
    await _log("info", "Handling interruption - saving progress")

    if chat_messages:
        notes = f"CHAT_CONTEXT:\n{chat_messages!r}"
        task_store.update_task(task_id, notes=notes)

    if current_worktree_path:
        worktree_manager.commit_in_worktree(
            project_id, task_id, "auto: Partial progress before interrupt"
        )

    completed_count = sum(1 for r in result.subtask_results if r.success)
    task_store.update_task_status(task_id, "paused")
    task_store.update_task(
        task_id,
        notes=f"Interrupted at subtask {completed_count + 1}. Chat context saved.",
    )
    task_store.release_task(task_id)

    await _log("info", f"Progress saved - {completed_count} subtasks completed")


def cleanup_on_failure(
    task_id: str,
    current_worktree_path: Path | None,
    worktree_manager: WorktreeManager,
    project_id: str,
) -> None:
    """Clean up resources on failure.

    Args:
        task_id: Task ID
        current_worktree_path: Current worktree path (will be set to None)
        worktree_manager: WorktreeManager instance
        project_id: Project ID
    """
    if current_worktree_path:
        try:
            worktree_manager.remove_worktree(project_id, task_id)
        except Exception as e:
            logger.warning("cleanup_failed", task_id=task_id, error=str(e))

    task_store.release_task(task_id)


async def create_draft_pr(
    task_id: str,
    current_worktree_path: Path | None,
    send_log: object,
) -> str | None:
    """Create a draft PR after successful execution.

    Uses `gh pr create --draft` to create PR from worktree branch.

    Args:
        task_id: Task ID for PR title
        current_worktree_path: Path to worktree
        send_log: Async function to send log messages

    Returns:
        PR URL if created, None if failed (non-blocking)
    """
    async def _log(level: str, message: str) -> None:
        if callable(send_log):
            await send_log(level, message, "orchestrator")  
    if not current_worktree_path:
        await _log("warning", "No worktree path - skipping PR creation")
        return None

    task = task_store.get_task(task_id)
    if not task:
        await _log("warning", "Task not found - skipping PR creation")
        return None

    title = task.get("title", f"Auto: {task_id}")
    description = str(task.get("description", ""))[:500]

    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--draft",
                "--title",
                f"auto({task_id[:8]}): {title[:50]}",
                "--body",
                f"""## Summary
Auto-generated PR for task {task_id}.

{description}

## Changes
See commits for details.

---
Generated by SummitFlow Orchestrator
""",
            ],
            cwd=str(current_worktree_path),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            pr_url = result.stdout.strip()
            logger.info("draft_pr_created", task_id=task_id, pr_url=pr_url)
            await _log("info", f"Draft PR created: {pr_url}")
            return pr_url
        else:
            error = result.stderr.strip() or "Unknown error"
            logger.warning("draft_pr_failed", task_id=task_id, error=error)
            await _log("warning", f"Failed to create PR: {error}")
            return None

    except subprocess.TimeoutExpired:
        await _log("warning", "PR creation timed out")
        return None
    except Exception as e:
        logger.warning("draft_pr_error", task_id=task_id, error=str(e))
        await _log("warning", f"PR creation error: {e}")
        return None


async def trigger_opus_review(
    task_id: str,
    pr_url: str | None,
    send_log: object,
) -> None:
    """Trigger Opus review via Celery task.

    Args:
        task_id: Task ID to review
        pr_url: Optional PR URL for reference
        send_log: Async function to send log messages
    """
    async def _log(level: str, message: str) -> None:
        if callable(send_log):
            await send_log(level, message, "orchestrator")  
    from ...tasks.ai_review import review_pull_request

    try:
        celery_task = review_pull_request.delay(task_id=task_id, pr_url=pr_url)
        logger.info(
            "opus_review_triggered",
            task_id=task_id,
            celery_task_id=celery_task.id,
            pr_url=pr_url,
        )
        await _log("info", f"Opus review queued: {celery_task.id}")
    except Exception as e:
        logger.warning("opus_review_trigger_failed", task_id=task_id, error=str(e))
        await _log("warning", f"Failed to trigger Opus review: {e}")
