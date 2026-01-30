"""Orchestrator Service for Autonomous Task Execution.

Uses Agent Hub agents for execution:
- agent:coder (AGENT_WORKER) handles coding tasks with mandate injection
- agent:supervisor (AGENT_SUPERVISOR) coordinates and handles stuck patterns
- Agent Hub provides model fallback chains, mandate injection, and metrics

Decision d1: Agent Hub agents with mandate injection
Decision d2: Claude SDK native interrupt() via WebSocket priority message
Decision d3: Coder agent for all coding, supervisor for stuck patterns
Decision d5: Self-heal 3 iterations, then auto-revert worktree

Modules:
    types: ExecutionState, SubtaskResult, OrchestrationResult
    websocket: WebSocket communication mixin
    execution: Subtask dispatch and result analysis
    handlers: Failure/interruption handling and PR creation
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from ...constants import AGENT_SUPERVISOR, AGENT_WORKER
from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.projects import get_project_root_path
from ...storage.subtasks import get_subtasks_for_task, update_subtask_passes
from ..worktree_manager import WorktreeManager, get_worktree_manager
from .execution import dispatch_to_worker, requires_human_review
from .handlers import (
    cleanup_on_failure,
    create_draft_pr,
    handle_failure,
    handle_interruption,
    trigger_opus_review,
)
from .types import ExecutionState, OrchestrationResult, SubtaskResult
from .websocket import WebSocketMixin

logger = get_logger(__name__)

__all__ = [
    "ExecutionState",
    "OrchestrationResult",
    "OrchestratorService",
    "SubtaskResult",
]


class OrchestratorService(WebSocketMixin):
    """Orchestrates autonomous task execution with Sonnet coordinator pattern.

    Architecture:
    - Sonnet coordinates: claims task, sets up worktree, reviews results
    - Flash workers: execute subtasks in parallel when possible
    - Pro escalation: consulted when stuck in failure patterns

    Lifecycle:
    1. Claim task atomically
    2. Create isolated worktree
    3. For each subtask:
       a. Dispatch to Flash worker
       b. Commit on success
       c. Retry up to 3x on failure
    4. Auto-revert worktree if all retries exhausted
    5. Submit to Opus review gate on success
    """

    MAX_RETRIES = 3
    STUCK_THRESHOLD = 2

    def __init__(
        self,
        project_id: str,
        repo_path: Path | None = None,
        ws_task_id: str | None = None,
    ):
        """Initialize orchestrator.

        Args:
            project_id: Project ID
            repo_path: Path to git repository (auto-detected if None)
            ws_task_id: Task ID for WebSocket streaming (optional)
        """
        self.project_id = project_id

        if repo_path:
            self.repo_path = repo_path
        else:
            root = get_project_root_path(project_id)
            if not root:
                raise ValueError(f"Project {project_id} not found or has no root_path")
            self.repo_path = Path(root)

        self.ws_task_id = ws_task_id
        self._worktree_manager: WorktreeManager | None = None
        self._current_worktree_path: Path | None = None
        self._state = ExecutionState.IDLE
        self._interrupted = False
        self._stop_handler_registered = False
        self._chat_messages: list[dict[str, object]] = []
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._current_streaming_session_id: str | None = None
        self._chat_handler_registered = False

    @property
    def worktree_manager(self) -> WorktreeManager:
        """Get or create WorktreeManager instance."""
        if self._worktree_manager is None:
            self._worktree_manager = get_worktree_manager(self.repo_path)
        return self._worktree_manager

    @property
    def effective_repo_path(self) -> Path:
        """Get the effective repo path (worktree if active, else main repo)."""
        return self._current_worktree_path or self.repo_path

    @property
    def state(self) -> ExecutionState:
        """Current execution state."""
        return self._state

    async def coordinate(
        self,
        task_id: str,
        worker_id: str | None = None,
        lock_duration_minutes: int = 60,
    ) -> OrchestrationResult:
        """Coordinate full task execution.

        Main entry point for orchestration:
        1. Claims task atomically
        2. Creates isolated worktree
        3. Executes subtasks via Flash workers
        4. Handles failures with retries and revert
        5. Submits to Opus review gate on success

        Args:
            task_id: Task to execute
            worker_id: Worker ID for claim (auto-generated if None)
            lock_duration_minutes: How long to hold task lock

        Returns:
            OrchestrationResult with execution details
        """
        self.ws_task_id = task_id
        self.register_stop_handler()
        self.register_chat_handler()

        try:
            return await self._do_coordinate(task_id, worker_id, lock_duration_minutes)
        finally:
            self.unregister_stop_handler()
            self.unregister_chat_handler()

    async def _do_coordinate(
        self,
        task_id: str,
        worker_id: str | None,
        lock_duration_minutes: int,
    ) -> OrchestrationResult:
        """Internal coordination logic."""
        result = OrchestrationResult(task_id=task_id, success=False, state=ExecutionState.IDLE)

        self._set_state(ExecutionState.CLAIMING)
        await self._send_log("info", f"Claiming task {task_id}")

        worker_id = worker_id or f"orchestrator-{self.project_id}"
        claimed = task_store.claim_task(task_id, worker_id, lock_duration_minutes)

        if not claimed:
            result.error = "Failed to claim task - already claimed or not found"
            result.state = ExecutionState.FAILED
            await self._send_log("error", result.error)
            return result

        logger.info("task_claimed", task_id=task_id, worker_id=worker_id)
        await self._send_log("info", f"Task claimed by {worker_id}")

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
                    await self._send_log("info", "COMPLEX task routed to human review")
                    return result

        self._set_state(ExecutionState.SETTING_UP)
        await self._send_log("info", "Creating isolated worktree")

        try:
            worktree_info = self.worktree_manager.create_worktree(self.project_id, task_id)
            self._current_worktree_path = worktree_info.path
            logger.info(
                "worktree_created",
                task_id=task_id,
                path=str(worktree_info.path),
                branch=worktree_info.branch,
            )
            await self._send_log("info", f"Worktree created: {worktree_info.branch}")
        except Exception as e:
            result.error = f"Failed to create worktree: {e}"
            result.state = ExecutionState.FAILED
            task_store.release_task(task_id)
            await self._send_log("error", result.error)
            return result

        subtasks = get_subtasks_for_task(task_id)
        if not subtasks:
            result.error = "Task has no subtasks - run planning first"
            result.state = ExecutionState.FAILED
            cleanup_on_failure(
                task_id, self._current_worktree_path, self.worktree_manager, self.project_id
            )
            self._current_worktree_path = None
            await self._send_log("error", result.error)
            return result

        pending_subtasks = [s for s in subtasks if not s.get("passes")]
        await self._send_log(
            "info", f"Found {len(pending_subtasks)}/{len(subtasks)} pending subtasks"
        )

        self._set_state(ExecutionState.EXECUTING)
        await self._send_model_change(AGENT_WORKER, "Starting with agent:coder worker")

        for subtask in pending_subtasks:
            if self._interrupted:
                result.state = ExecutionState.INTERRUPTED
                result.error = "Execution interrupted by user"
                await handle_interruption(
                    task_id,
                    result,
                    self._chat_messages,
                    self._current_worktree_path,
                    self.worktree_manager,
                    self.project_id,
                    self._send_log,
                )
                return result

            subtask_result = await self.execute_subtask(task_id=task_id, subtask=subtask)
            result.subtask_results.append(subtask_result)
            result.total_iterations += subtask_result.iterations

            if not subtask_result.success:
                result.state = ExecutionState.FAILED
                result.error = f"Subtask {subtask_result.subtask_id} failed: {subtask_result.error}"
                result.worktree_reverted = await handle_failure(
                    task_id,
                    subtask_result,
                    self.worktree_manager,
                    self.project_id,
                    self._send_log,
                )
                self._current_worktree_path = None
                await self._send_log("error", result.error)
                return result

        self._set_state(ExecutionState.REVIEWING)
        await self._send_log("info", "All subtasks complete, creating draft PR")

        pr_url = await create_draft_pr(task_id, self._current_worktree_path, self._send_log)
        if pr_url:
            result.merge_sha = pr_url
            task_store.update_task(task_id, notes=f"PR: {pr_url}")

        task_store.update_task_status(task_id, "ai_reviewing")
        await trigger_opus_review(task_id, pr_url, self._send_log)

        result.success = True
        result.state = ExecutionState.COMPLETED
        await self._send_log("info", "Orchestration complete - Opus review triggered")

        return result

    async def execute_subtask(
        self,
        task_id: str,
        subtask: dict[str, object],
    ) -> SubtaskResult:
        """Execute a single subtask with Flash worker.

        Implements retry logic with model escalation:
        - First attempts use Flash (fast, cost-effective)
        - After STUCK_THRESHOLD failures, consult Pro
        - After MAX_RETRIES, give up

        Args:
            task_id: Parent task ID
            subtask: Subtask dict with id, description, steps

        Returns:
            SubtaskResult with execution details
        """
        subtask_id = str(subtask.get("subtask_full_id") or subtask.get("id") or "unknown")
        description = subtask.get("description", "")

        await self._send_log("info", f"Starting subtask {subtask_id}: {str(description)[:50]}...")

        result = SubtaskResult(
            subtask_id=subtask_id,
            success=False,
            model_used=AGENT_WORKER,
        )

        consecutive_failures = 0
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            if self._interrupted:
                result.error = "Interrupted"
                return result

            result.iterations += 1

            if consecutive_failures >= self.STUCK_THRESHOLD:
                model = AGENT_SUPERVISOR
                await self._send_model_change(
                    AGENT_SUPERVISOR,
                    f"Escalating to supervisor after {consecutive_failures} failures",
                )
            else:
                model = AGENT_WORKER

            result.model_used = model
            await self._send_log("info", f"Attempt {attempt + 1}/{self.MAX_RETRIES} with {model}")

            try:
                success, error = await dispatch_to_worker(
                    subtask=subtask,
                    model=model,
                    effective_repo_path=self.effective_repo_path,
                    chat_messages=self._chat_messages,
                    send_log=self._send_log,
                )

                if success:
                    commit_message = f"auto({subtask_id}): {str(description)[:50]}"
                    committed = self.worktree_manager.commit_in_worktree(
                        self.project_id, task_id, commit_message
                    )

                    if committed:
                        result.success = True
                        result.error = None

                        update_subtask_passes(task_id, subtask_id, passes=True)
                        await self._send_log(
                            "info", f"Subtask {subtask_id} completed and committed"
                        )

                        return result
                    else:
                        last_error = "Commit failed"
                        consecutive_failures += 1
                else:
                    last_error = error
                    consecutive_failures += 1
                    await self._send_log("warning", f"Attempt {attempt + 1} failed: {error}")

            except Exception as e:
                last_error = str(e)
                consecutive_failures += 1
                logger.error("subtask_execution_error", subtask_id=subtask_id, error=str(e))
                await self._send_log("error", f"Execution error: {e}")

        result.error = f"Exhausted {self.MAX_RETRIES} retries. Last error: {last_error}"
        return result

    async def resume_from_interrupt(self, task_id: str) -> OrchestrationResult:
        """Resume execution from a previous interrupt.

        Per decision d2: Continue with chat context loaded.

        Args:
            task_id: Task ID to resume

        Returns:
            OrchestrationResult from continued execution
        """
        task = task_store.get_task(task_id)
        if not task:
            return OrchestrationResult(
                task_id=task_id,
                success=False,
                state=ExecutionState.FAILED,
                error="Task not found",
            )

        notes = task.get("notes", "")
        if isinstance(notes, str) and "CHAT_CONTEXT:" in notes:
            try:
                context_start = notes.index("CHAT_CONTEXT:") + len("CHAT_CONTEXT:\n")
                context_str = notes[context_start:]
                self._chat_messages = ast.literal_eval(context_str)
            except Exception as e:
                logger.warning("failed_to_parse_chat_context", error=str(e))

        await self._send_log("info", f"Resuming task with {len(self._chat_messages)} chat messages")

        return await self.coordinate(task_id)
