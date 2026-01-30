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
    coordination: Main coordination flow
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.projects import get_project_root_path
from ..worktree_manager import WorktreeManager, get_worktree_manager
from .coordination import do_coordinate, execute_subtask
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
            return await do_coordinate(self, task_id, worker_id, lock_duration_minutes)
        finally:
            self.unregister_stop_handler()
            self.unregister_chat_handler()

    async def execute_subtask(
        self,
        task_id: str,
        subtask: dict[str, object],
    ) -> SubtaskResult:
        """Execute a single subtask with Flash worker.

        Args:
            task_id: Parent task ID
            subtask: Subtask dict with id, description, steps

        Returns:
            SubtaskResult with execution details
        """
        return await execute_subtask(self, task_id, subtask)

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
