"""Orchestrator Service for Autonomous Task Execution.

Uses Agent Hub agents for execution:
- agent:coder (AGENT_WORKER) handles coding tasks with mandate injection
- agent:supervisor (AGENT_SUPERVISOR) coordinates and handles stuck patterns
- Agent Hub provides model fallback chains, mandate injection, and metrics

Decision d1: Agent Hub agents with mandate injection
Decision d2: Claude SDK native interrupt() via WebSocket priority message
Decision d3: Coder agent for all coding, supervisor for stuck patterns
Decision d5: Self-heal 3 iterations, then auto-revert worktree
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..constants import (
    AGENT_SUPERVISOR,
    AGENT_WORKER,
)
from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..storage.projects import get_project_root_path
from ..storage.subtasks import get_subtasks_for_task, update_subtask_passes
from .worktree_manager import WorktreeManager, get_worktree_manager

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class ExecutionState(str, Enum):
    """Orchestrator execution states."""

    IDLE = "idle"
    CLAIMING = "claiming"
    SETTING_UP = "setting_up"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    MERGING = "merging"
    FAILED = "failed"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass
class SubtaskResult:
    """Result of executing a single subtask."""

    subtask_id: str
    success: bool
    error: str | None = None
    iterations: int = 0
    model_used: str = ""
    commit_sha: str | None = None


@dataclass
class OrchestrationResult:
    """Result of full task orchestration."""

    task_id: str
    success: bool
    state: ExecutionState
    subtask_results: list[SubtaskResult] = field(default_factory=list)
    error: str | None = None
    total_iterations: int = 0
    worktree_reverted: bool = False
    merge_sha: str | None = None


class OrchestratorService:
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
    STUCK_THRESHOLD = 2  # Consult Pro after this many failures

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
        self._chat_messages: list[dict[str, Any]] = []
        # Background tasks that shouldn't be garbage collected
        self._background_tasks: set[asyncio.Task[None]] = set()
        # Current streaming session ID for cancellation support
        self._current_streaming_session_id: str | None = None
        # Chat handler registration state
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

    def _set_state(self, state: ExecutionState) -> None:
        """Update state and notify WebSocket if connected."""
        self._state = state
        logger.info("orchestrator_state_change", state=state.value, task_id=self.ws_task_id)

        if self.ws_task_id:
            # Import here to avoid circular imports
            task = asyncio.create_task(self._send_progress_update())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _send_progress_update(self) -> None:
        """Send progress update via WebSocket."""
        if not self.ws_task_id:
            return

        from ..api.ws_execution import send_progress

        await send_progress(
            self.ws_task_id,
            status=self._state.value,
        )

    async def _send_log(self, level: str, message: str, source: str = "orchestrator") -> None:
        """Send log message via WebSocket."""
        if not self.ws_task_id:
            return

        from ..api.ws_execution import send_log

        await send_log(self.ws_task_id, level, message, source)

    async def _send_model_change(self, model: str, reason: str = "") -> None:
        """Send model change notification via WebSocket."""
        if not self.ws_task_id:
            return

        from ..api.ws_execution import send_model_change

        await send_model_change(self.ws_task_id, model, reason)

    def register_stop_handler(self) -> None:
        """Register handler to receive stop signals from WebSocket."""
        if self._stop_handler_registered or not self.ws_task_id:
            return

        from ..api.ws_execution import register_stop_handler

        def handle_stop() -> None:
            logger.info("stop_signal_received", task_id=self.ws_task_id)
            self.receive_stop_signal()

        register_stop_handler(self.ws_task_id, handle_stop)
        self._stop_handler_registered = True

    def unregister_stop_handler(self) -> None:
        """Unregister stop signal handler."""
        if not self._stop_handler_registered or not self.ws_task_id:
            return

        from ..api.ws_execution import unregister_stop_handler

        unregister_stop_handler(self.ws_task_id)
        self._stop_handler_registered = False

    def register_chat_handler(self) -> None:
        """Register handler to receive chat messages from WebSocket."""
        if self._chat_handler_registered or not self.ws_task_id:
            return

        from ..api.ws_execution import register_chat_handler

        def handle_chat(message_data: dict[str, Any]) -> None:
            logger.info("chat_message_received", task_id=self.ws_task_id)
            self.store_chat_message(message_data)

        register_chat_handler(self.ws_task_id, handle_chat)
        self._chat_handler_registered = True

    def unregister_chat_handler(self) -> None:
        """Unregister chat message handler."""
        if not self._chat_handler_registered or not self.ws_task_id:
            return

        from ..api.ws_execution import unregister_chat_handler

        unregister_chat_handler(self.ws_task_id)
        self._chat_handler_registered = False

    def receive_stop_signal(self) -> None:
        """Handle stop signal - interrupts current execution.

        Per decision d2: Uses dual interrupt mechanism:
        1. Set _interrupted flag for polling in _dispatch_to_flash
        2. Cancel active stream via Agent Hub registry (async)
        """
        self._interrupted = True
        logger.info("stop_signal_handled", task_id=self.ws_task_id, state=self._state.value)

        # Cancel active streaming session if present
        if self._current_streaming_session_id:
            # Schedule async cancellation
            task = asyncio.create_task(self._cancel_active_stream())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _cancel_active_stream(self) -> None:
        """Cancel active streaming session via Agent Hub REST API."""
        if not self._current_streaming_session_id:
            return

        from agent_hub import AsyncAgentHubClient

        try:
            async with AsyncAgentHubClient() as client:
                result = await client.cancel_stream(self._current_streaming_session_id)
                logger.info(
                    "stream_cancellation_result",
                    session_id=self._current_streaming_session_id,
                    result=result,
                )
        except Exception as e:
            logger.warning(
                "stream_cancellation_failed",
                session_id=self._current_streaming_session_id,
                error=str(e),
            )

    def store_chat_message(self, message: dict[str, Any]) -> None:
        """Store chat message for resume context.

        Per decision d6: Chat messages stored in task.notes for resume.
        """
        self._chat_messages.append(
            {
                **message,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

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

        # Step 1: Claim task
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

        # Step 1.5: Complexity assessment - route COMPLEX to human review
        task = task_store.get_task(task_id)
        if task:
            complexity = task.get("complexity", "STANDARD")
            if complexity == "COMPLEX":
                # Check if task has architecture label or touches many domains
                labels = task.get("labels", [])
                if "architecture" in labels or self._requires_human_review(task):
                    task_store.release_task(task_id)
                    task_store.update_task_status(task_id, "human_review")
                    result.error = "Task complexity requires human review"
                    result.state = ExecutionState.FAILED
                    await self._send_log("info", "COMPLEX task routed to human review")
                    return result

        # Step 2: Setup worktree
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

        # Step 3: Get subtasks
        subtasks = get_subtasks_for_task(task_id)
        if not subtasks:
            result.error = "Task has no subtasks - run planning first"
            result.state = ExecutionState.FAILED
            self._cleanup_on_failure(task_id)
            await self._send_log("error", result.error)
            return result

        # Filter to incomplete subtasks
        pending_subtasks = [s for s in subtasks if not s.get("passes")]
        await self._send_log(
            "info", f"Found {len(pending_subtasks)}/{len(subtasks)} pending subtasks"
        )

        # Step 4: Execute subtasks
        self._set_state(ExecutionState.EXECUTING)
        await self._send_model_change(AGENT_WORKER, "Starting with agent:coder worker")

        for subtask in pending_subtasks:
            if self._interrupted:
                result.state = ExecutionState.INTERRUPTED
                result.error = "Execution interrupted by user"
                await self._handle_interruption(task_id, result)
                return result

            subtask_result = await self.execute_subtask(
                task_id=task_id,
                subtask=subtask,
            )
            result.subtask_results.append(subtask_result)
            result.total_iterations += subtask_result.iterations

            if not subtask_result.success:
                # Per decision d5: Auto-revert on failure
                result.state = ExecutionState.FAILED
                result.error = f"Subtask {subtask_result.subtask_id} failed: {subtask_result.error}"
                result.worktree_reverted = await self._handle_failure(task_id, subtask_result)
                await self._send_log("error", result.error)
                return result

        # Step 5: All subtasks succeeded - create draft PR
        self._set_state(ExecutionState.REVIEWING)
        await self._send_log("info", "All subtasks complete, creating draft PR")

        pr_url = await self._create_draft_pr(task_id)
        if pr_url:
            result.merge_sha = pr_url  # Store PR URL in merge_sha for now
            # Update task with PR URL
            task_store.update_task(task_id, notes=f"PR: {pr_url}")

        # Transition to ai_reviewing for Opus gate
        task_store.update_task_status(task_id, "ai_reviewing")

        # Trigger immediate Opus review
        await self._trigger_opus_review(task_id, pr_url)

        result.success = True
        result.state = ExecutionState.COMPLETED
        await self._send_log("info", "Orchestration complete - Opus review triggered")

        return result

    async def execute_subtask(
        self,
        task_id: str,
        subtask: dict[str, Any],
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

        await self._send_log("info", f"Starting subtask {subtask_id}: {description[:50]}...")

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

            # Decide which model to use
            if consecutive_failures >= self.STUCK_THRESHOLD:
                model = AGENT_SUPERVISOR
                await self._send_model_change(
                    AGENT_SUPERVISOR, f"Escalating to supervisor after {consecutive_failures} failures"
                )
            else:
                model = AGENT_WORKER

            result.model_used = model
            await self._send_log("info", f"Attempt {attempt + 1}/{self.MAX_RETRIES} with {model}")

            try:
                success, error = await self._dispatch_to_flash(
                    subtask=subtask,
                    model=model,
                )

                if success:
                    # Commit changes
                    commit_message = f"auto({subtask_id}): {description[:50]}"
                    committed = self.worktree_manager.commit_in_worktree(
                        self.project_id, task_id, commit_message
                    )

                    if committed:
                        result.success = True
                        result.error = None

                        # Mark subtask as passed
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

        # All retries exhausted
        result.error = f"Exhausted {self.MAX_RETRIES} retries. Last error: {last_error}"
        return result

    async def _dispatch_to_flash(
        self,
        subtask: dict[str, Any],
        model: str = AGENT_WORKER,
    ) -> tuple[bool, str | None]:
        """Dispatch subtask to worker agent for execution.

        Uses Agent Hub SDK's run_agent for agentic execution with tool calling.

        Args:
            subtask: Subtask to execute
            model: Agent/model to use (AGENT_WORKER, AGENT_SUPERVISOR, etc.
                   or direct model names like CLAUDE_SONNET)

        Returns:
            Tuple of (success, error_message)
        """
        from agent_hub import AsyncAgentHubClient

        subtask_id = str(subtask.get("subtask_full_id") or subtask.get("id") or "unknown")
        description = subtask.get("description", "")

        logger.info(
            "dispatch_to_flash",
            subtask_id=subtask_id,
            model=model,
            description=description[:50],
        )

        # Build prompt with task context
        prompt = self._build_flash_prompt(subtask)

        # Determine provider from model
        provider = "claude" if "claude" in model.lower() else "gemini"

        await self._send_log("info", f"Starting agent execution with {provider}/{model}")

        try:
            async with AsyncAgentHubClient() as client:
                result = await client.run_agent(
                    task=prompt,
                    provider=provider,
                    model=model,
                    system_prompt="You are an expert software engineer executing tasks. Be thorough and precise.",
                    max_tokens=64000,
                    max_turns=20,
                    enable_code_execution=(provider == "claude"),  # Only for Claude
                    working_dir=str(self.effective_repo_path),
                    timeout_seconds=300.0,
                )

                # Log progress
                for progress in result.progress_log:
                    if progress.status == "running":
                        await self._send_log(
                            "info", f"Turn {progress.turn}: {progress.message}", source="flash"
                        )
                    elif progress.status == "tool_use":
                        tool_names = [tc.get("name", "?") for tc in progress.tool_calls]
                        await self._send_log(
                            "info", f"Tool calls: {', '.join(tool_names)}", source="flash"
                        )
                    elif progress.status == "complete":
                        await self._send_log(
                            "info",
                            f"Agent completed: {result.input_tokens} in, {result.output_tokens} out",
                            source="flash",
                        )

                # Check result status
                if result.status == "error":
                    await self._send_log("error", f"Agent error: {result.error}")
                    return False, result.error

                if result.status == "max_turns":
                    await self._send_log("warning", "Agent reached max turns")
                    # Still analyze the partial result

                # Analyze content to determine task success
                success, error = self._analyze_execution_result(result.content, subtask)
                return success, error

        except Exception as e:
            logger.error("dispatch_to_flash_error", subtask_id=subtask_id, error=str(e))
            await self._send_log("error", f"Execution failed: {e}")
            return False, str(e)

    def _build_flash_prompt(self, subtask: dict[str, Any]) -> str:
        """Build prompt for Flash worker with task context and user directions.

        Args:
            subtask: Subtask to execute

        Returns:
            Formatted prompt string
        """
        subtask_id = subtask.get("subtask_full_id") or subtask.get("id")
        description = subtask.get("description", "")
        steps = subtask.get("steps", [])

        # Format steps as numbered list
        steps_text = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))

        # Include any user chat directions
        user_directions = ""
        if self._chat_messages:
            recent_messages = self._chat_messages[-3:]  # Last 3 messages
            directions = [f"- {m.get('content', '')}" for m in recent_messages if m.get("content")]
            if directions:
                user_directions = f"""
## User Directions
The user has provided the following guidance:
{chr(10).join(directions)}

Please incorporate this direction into your work.
"""

        prompt = f"""# Task: Execute Subtask {subtask_id}

## Description
{description}

## Steps to Complete
{steps_text}

## Working Directory
{self.effective_repo_path}
{user_directions}
## Instructions
You are an expert software engineer. Complete the steps above.
For each step:
1. Read relevant files to understand the codebase
2. Make necessary code changes
3. Verify your changes work

After completing all steps, respond with:
- DONE: If all steps completed successfully
- BLOCKED: <reason> if you cannot proceed
- ERROR: <details> if an error occurred

Be concise in your responses. Focus on completing the task."""

        return prompt

    def _analyze_execution_result(
        self, content: str, subtask: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Analyze agent response to determine success/failure.

        Args:
            content: Agent response content
            subtask: The subtask that was executed

        Returns:
            Tuple of (success, error_message)
        """
        content_lower = content.lower()

        # Check for explicit success indicators
        if "done:" in content_lower or "completed successfully" in content_lower:
            return True, None

        # Check for explicit failure indicators
        if "blocked:" in content_lower:
            # Extract reason
            idx = content_lower.find("blocked:")
            reason = content[idx + 8 :].strip()[:200]
            return False, f"Blocked: {reason}"

        if "error:" in content_lower:
            idx = content_lower.find("error:")
            error = content[idx + 6 :].strip()[:200]
            return False, f"Error: {error}"

        # Check for common failure patterns
        failure_patterns = [
            "cannot complete",
            "unable to",
            "failed to",
            "i cannot",
            "not possible",
        ]
        for pattern in failure_patterns:
            if pattern in content_lower:
                return False, f"Agent reported inability: {pattern}"

        # If no clear indicators, assume success if response is substantial
        if len(content) > 100:
            return True, None

        # Short response with no clear indicators - uncertain
        return False, "Inconclusive response from agent"

    def _requires_human_review(self, task: dict[str, Any]) -> bool:
        """Check if task requires human review based on complexity heuristics.

        Args:
            task: Task dict

        Returns:
            True if task should be routed to human review
        """
        labels = task.get("labels", [])

        # Security-sensitive tasks
        security_patterns = ["security", "auth", "credential", "payment", "crypto"]
        if any(pattern in label.lower() for label in labels for pattern in security_patterns):
            return True

        # Multi-domain tasks
        domain_labels = [label for label in labels if label.startswith("domains:")]
        if len(domain_labels) >= 3:
            return True

        # Explicit human review request
        if "needs-human-review" in labels:
            return True

        # Architecture changes
        return "architecture" in labels or "breaking-change" in labels

    async def _trigger_opus_review(self, task_id: str, pr_url: str | None) -> None:
        """Trigger Opus review via Celery task.

        Args:
            task_id: Task ID to review
            pr_url: Optional PR URL for reference
        """
        from ..tasks.ai_review import review_pull_request

        try:
            celery_task = review_pull_request.delay(task_id=task_id, pr_url=pr_url)
            logger.info(
                "opus_review_triggered",
                task_id=task_id,
                celery_task_id=celery_task.id,
                pr_url=pr_url,
            )
            await self._send_log("info", f"Opus review queued: {celery_task.id}")
        except Exception as e:
            logger.warning("opus_review_trigger_failed", task_id=task_id, error=str(e))
            await self._send_log("warning", f"Failed to trigger Opus review: {e}")

    async def _create_draft_pr(self, task_id: str) -> str | None:
        """Create a draft PR after successful execution.

        Uses `gh pr create --draft` to create PR from worktree branch.

        Args:
            task_id: Task ID for PR title

        Returns:
            PR URL if created, None if failed (non-blocking)
        """
        import subprocess

        if not self._current_worktree_path:
            await self._send_log("warning", "No worktree path - skipping PR creation")
            return None

        # Get task for PR title
        task = task_store.get_task(task_id)
        if not task:
            await self._send_log("warning", "Task not found - skipping PR creation")
            return None

        title = task.get("title", f"Auto: {task_id}")
        description = task.get("description", "")[:500]

        try:
            # Create draft PR
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
🤖 Generated by SummitFlow Orchestrator
""",
                ],
                cwd=str(self._current_worktree_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                pr_url = result.stdout.strip()
                logger.info("draft_pr_created", task_id=task_id, pr_url=pr_url)
                await self._send_log("info", f"Draft PR created: {pr_url}")
                return pr_url
            else:
                # Log error but don't fail execution
                error = result.stderr.strip() or "Unknown error"
                logger.warning("draft_pr_failed", task_id=task_id, error=error)
                await self._send_log("warning", f"Failed to create PR: {error}")
                return None

        except subprocess.TimeoutExpired:
            await self._send_log("warning", "PR creation timed out")
            return None
        except Exception as e:
            logger.warning("draft_pr_error", task_id=task_id, error=str(e))
            await self._send_log("warning", f"PR creation error: {e}")
            return None

    async def _handle_failure(self, task_id: str, subtask_result: SubtaskResult) -> bool:
        """Handle subtask failure by reverting worktree.

        Per decision d5: Self-heal 3 iterations, then auto-revert worktree.

        Args:
            task_id: Task ID
            subtask_result: Failed subtask result

        Returns:
            True if worktree was reverted successfully
        """
        await self._send_log("warning", f"Reverting worktree after failure: {subtask_result.error}")

        try:
            # Remove worktree (reverts all changes)
            self.worktree_manager.remove_worktree(self.project_id, task_id, delete_branch=True)
            self._current_worktree_path = None

            # Update task status (do NOT release - failed tasks stay failed until manual intervention)
            task_store.update_task_status(
                task_id,
                "failed",
                error_message=subtask_result.error,
            )

            logger.info("worktree_reverted_on_failure", task_id=task_id)
            await self._send_log("info", "Worktree reverted successfully")
            return True

        except Exception as e:
            logger.error("worktree_revert_failed", task_id=task_id, error=str(e))
            await self._send_log("error", f"Failed to revert worktree: {e}")
            return False

    async def _handle_interruption(self, task_id: str, result: OrchestrationResult) -> None:
        """Handle user interruption gracefully.

        Per decision d2 and d6:
        - Store chat context for resume
        - Commit partial work
        - Update task status to paused

        Args:
            task_id: Task ID
            result: Current orchestration result
        """
        await self._send_log("info", "Handling interruption - saving progress")

        # Store chat messages in task notes for resume
        if self._chat_messages:
            notes = f"CHAT_CONTEXT:\n{self._chat_messages!r}"
            task_store.update_task(task_id, notes=notes)

        # Commit any pending changes
        if self._current_worktree_path:
            self.worktree_manager.commit_in_worktree(
                self.project_id, task_id, "auto: Partial progress before interrupt"
            )

        # Update task status to paused
        completed_count = sum(1 for r in result.subtask_results if r.success)
        task_store.update_task_status(task_id, "paused")
        task_store.update_task(
            task_id,
            notes=f"Interrupted at subtask {completed_count + 1}. Chat context saved.",
        )
        task_store.release_task(task_id)

        await self._send_log("info", f"Progress saved - {completed_count} subtasks completed")

    def _cleanup_on_failure(self, task_id: str) -> None:
        """Clean up resources on failure."""
        if self._current_worktree_path:
            try:
                self.worktree_manager.remove_worktree(self.project_id, task_id)
            except Exception as e:
                logger.warning("cleanup_failed", task_id=task_id, error=str(e))
            self._current_worktree_path = None

        task_store.release_task(task_id)

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

        # Load chat context from notes
        notes = task.get("notes", "")
        if "CHAT_CONTEXT:" in notes:
            # Parse stored chat messages using ast.literal_eval for safety
            import ast

            try:
                context_start = notes.index("CHAT_CONTEXT:") + len("CHAT_CONTEXT:\n")
                context_str = notes[context_start:]
                self._chat_messages = ast.literal_eval(context_str)
            except Exception as e:
                logger.warning("failed_to_parse_chat_context", error=str(e))

        await self._send_log("info", f"Resuming task with {len(self._chat_messages)} chat messages")

        # Resume coordination
        return await self.coordinate(task_id)
