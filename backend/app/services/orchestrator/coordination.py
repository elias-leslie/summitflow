"""Task coordination logic for orchestrator.

Contains the main coordination flow and subtask execution methods.
"""

from __future__ import annotations

from ...constants import AGENT_SUPERVISOR, AGENT_WORKER
from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task, update_subtask_passes
from .execution import dispatch_to_worker, requires_human_review
from .handlers import (
    cleanup_on_failure,
    create_draft_pr,
    handle_failure,
    handle_interruption,
    trigger_opus_review,
)
from .types import ExecutionState, OrchestrationResult, SubtaskResult

logger = get_logger(__name__)


async def do_coordinate(
    orchestrator: object,
    task_id: str,
    worker_id: str | None,
    lock_duration_minutes: int,
) -> OrchestrationResult:
    """Execute the main coordination flow.

    Args:
        orchestrator: OrchestratorService instance
        task_id: Task to execute
        worker_id: Worker ID for claim
        lock_duration_minutes: How long to hold task lock

    Returns:
        OrchestrationResult with execution details
    """
    result = OrchestrationResult(task_id=task_id, success=False, state=ExecutionState.IDLE)

    orch = orchestrator
    orch._set_state(ExecutionState.CLAIMING)  # type: ignore[attr-defined]
    await orch._send_log("info", f"Claiming task {task_id}")  # type: ignore[attr-defined]

    worker_id = worker_id or f"orchestrator-{orch.project_id}"  # type: ignore[attr-defined]
    claimed = task_store.claim_task(task_id, worker_id, lock_duration_minutes)

    if not claimed:
        result.error = "Failed to claim task - already claimed or not found"
        result.state = ExecutionState.FAILED
        await orch._send_log("error", result.error)  # type: ignore[attr-defined]
        return result

    logger.info("task_claimed", task_id=task_id, worker_id=worker_id)
    await orch._send_log("info", f"Task claimed by {worker_id}")  # type: ignore[attr-defined]

    task = task_store.get_task(task_id)
    if task:
        complexity = task.get("complexity", "STANDARD")
        if complexity == "COMPLEX":
            labels = task.get("labels", [])
            if "architecture" in (labels or []) or requires_human_review(task):
                task_store.release_task(task_id)
                task_store.update_task_status(task_id, "human_review")
                result.error = "Task complexity requires human review"
                result.state = ExecutionState.FAILED
                await orch._send_log("info", "COMPLEX task routed to human review")  # type: ignore[attr-defined]
                return result

    orch._set_state(ExecutionState.SETTING_UP)  # type: ignore[attr-defined]
    await orch._send_log("info", "Creating isolated worktree")  # type: ignore[attr-defined]

    try:
        worktree_info = orch.worktree_manager.create_worktree(  # type: ignore[attr-defined]
            orch.project_id, task_id  # type: ignore[attr-defined]
        )
        orch._current_worktree_path = worktree_info.path  # type: ignore[attr-defined]
        logger.info(
            "worktree_created",
            task_id=task_id,
            path=str(worktree_info.path),
            branch=worktree_info.branch,
        )
        await orch._send_log("info", f"Worktree created: {worktree_info.branch}")  # type: ignore[attr-defined]
    except Exception as e:
        result.error = f"Failed to create worktree: {e}"
        result.state = ExecutionState.FAILED
        task_store.release_task(task_id)
        await orch._send_log("error", result.error)  # type: ignore[attr-defined]
        return result

    subtasks = get_subtasks_for_task(task_id)
    if not subtasks:
        result.error = "Task has no subtasks - run planning first"
        result.state = ExecutionState.FAILED
        cleanup_on_failure(
            task_id,
            orch._current_worktree_path,  # type: ignore[attr-defined]
            orch.worktree_manager,  # type: ignore[attr-defined]
            orch.project_id,  # type: ignore[attr-defined]
        )
        orch._current_worktree_path = None  # type: ignore[attr-defined]
        await orch._send_log("error", result.error)  # type: ignore[attr-defined]
        return result

    pending_subtasks = [s for s in subtasks if not s.get("passes")]
    await orch._send_log(  # type: ignore[attr-defined]
        "info", f"Found {len(pending_subtasks)}/{len(subtasks)} pending subtasks"
    )

    orch._set_state(ExecutionState.EXECUTING)  # type: ignore[attr-defined]
    await orch._send_model_change(AGENT_WORKER, "Starting with agent:coder worker")  # type: ignore[attr-defined]

    for subtask in pending_subtasks:
        if orch._interrupted:  # type: ignore[attr-defined]
            result.state = ExecutionState.INTERRUPTED
            result.error = "Execution interrupted by user"
            await handle_interruption(
                task_id,
                result,
                orch._chat_messages,  # type: ignore[attr-defined]
                orch._current_worktree_path,  # type: ignore[attr-defined]
                orch.worktree_manager,  # type: ignore[attr-defined]
                orch.project_id,  # type: ignore[attr-defined]
                orch._send_log,  # type: ignore[attr-defined]
            )
            return result

        subtask_result = await execute_subtask(orchestrator, task_id=task_id, subtask=subtask)
        result.subtask_results.append(subtask_result)
        result.total_iterations += subtask_result.iterations

        if not subtask_result.success:
            result.state = ExecutionState.FAILED
            result.error = f"Subtask {subtask_result.subtask_id} failed: {subtask_result.error}"
            result.worktree_reverted = await handle_failure(
                task_id,
                subtask_result,
                orch.worktree_manager,  # type: ignore[attr-defined]
                orch.project_id,  # type: ignore[attr-defined]
                orch._send_log,  # type: ignore[attr-defined]
            )
            orch._current_worktree_path = None  # type: ignore[attr-defined]
            await orch._send_log("error", result.error)  # type: ignore[attr-defined]
            return result

    orch._set_state(ExecutionState.REVIEWING)  # type: ignore[attr-defined]
    await orch._send_log("info", "All subtasks complete, creating draft PR")  # type: ignore[attr-defined]

    pr_url = await create_draft_pr(
        task_id, orch._current_worktree_path, orch._send_log  # type: ignore[attr-defined]
    )
    if pr_url:
        result.merge_sha = pr_url
        task_store.update_task(task_id, notes=f"PR: {pr_url}")

    task_store.update_task_status(task_id, "ai_reviewing")
    await trigger_opus_review(task_id, pr_url, orch._send_log)  # type: ignore[attr-defined]

    result.success = True
    result.state = ExecutionState.COMPLETED
    await orch._send_log("info", "Orchestration complete - Opus review triggered")  # type: ignore[attr-defined]

    return result


async def execute_subtask(
    orchestrator: object,
    task_id: str,
    subtask: dict[str, object],
) -> SubtaskResult:
    """Execute a single subtask with Flash worker.

    Implements retry logic with model escalation:
    - First attempts use Flash (fast, cost-effective)
    - After STUCK_THRESHOLD failures, consult Pro
    - After MAX_RETRIES, give up

    Args:
        orchestrator: OrchestratorService instance
        task_id: Parent task ID
        subtask: Subtask dict with id, description, steps

    Returns:
        SubtaskResult with execution details
    """
    orch = orchestrator
    subtask_id = str(subtask.get("subtask_full_id") or subtask.get("id") or "unknown")
    description = subtask.get("description", "")

    await orch._send_log("info", f"Starting subtask {subtask_id}: {str(description)[:50]}...")  # type: ignore[attr-defined]

    result = SubtaskResult(
        subtask_id=subtask_id,
        success=False,
        model_used=AGENT_WORKER,
    )

    consecutive_failures = 0
    last_error = None

    for attempt in range(orch.MAX_RETRIES):  # type: ignore[attr-defined]
        if orch._interrupted:  # type: ignore[attr-defined]
            result.error = "Interrupted"
            return result

        result.iterations += 1

        if consecutive_failures >= orch.STUCK_THRESHOLD:  # type: ignore[attr-defined]
            model = AGENT_SUPERVISOR
            await orch._send_model_change(  # type: ignore[attr-defined]
                AGENT_SUPERVISOR,
                f"Escalating to supervisor after {consecutive_failures} failures",
            )
        else:
            model = AGENT_WORKER

        result.model_used = model
        await orch._send_log(  # type: ignore[attr-defined]
            "info", f"Attempt {attempt + 1}/{orch.MAX_RETRIES} with {model}"  # type: ignore[attr-defined]
        )

        try:
            success, error = await dispatch_to_worker(
                subtask=subtask,
                model=model,
                effective_repo_path=orch.effective_repo_path,  # type: ignore[attr-defined]
                chat_messages=orch._chat_messages,  # type: ignore[attr-defined]
                send_log=orch._send_log,  # type: ignore[attr-defined]
            )

            if success:
                commit_message = f"auto({subtask_id}): {str(description)[:50]}"
                committed = orch.worktree_manager.commit_in_worktree(  # type: ignore[attr-defined]
                    orch.project_id, task_id, commit_message  # type: ignore[attr-defined]
                )

                if committed:
                    result.success = True
                    result.error = None

                    update_subtask_passes(task_id, subtask_id, passes=True)
                    await orch._send_log(  # type: ignore[attr-defined]
                        "info", f"Subtask {subtask_id} completed and committed"
                    )

                    return result
                else:
                    last_error = "Commit failed"
                    consecutive_failures += 1
            else:
                last_error = error
                consecutive_failures += 1
                await orch._send_log("warning", f"Attempt {attempt + 1} failed: {error}")  # type: ignore[attr-defined]

        except Exception as e:
            last_error = str(e)
            consecutive_failures += 1
            logger.error("subtask_execution_error", subtask_id=subtask_id, error=str(e))
            await orch._send_log("error", f"Execution error: {e}")  # type: ignore[attr-defined]

    result.error = f"Exhausted {orch.MAX_RETRIES} retries. Last error: {last_error}"  # type: ignore[attr-defined]
    return result
