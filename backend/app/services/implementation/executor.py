"""Implementation executor - Main executor class and iteration loop.

Provides the core execution engine for running tasks with:
- Iteration loop (up to max_iterations)
- External verification (pytest, pyright, ruff)
- Alternate model consultation on thrashing
- Rollback on exhaustion
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.agent_sessions import create_session, get_session, update_session
from .loop import run_iteration_loop
from .subtasks import get_next_task_from_subtasks
from .types import ExecutionResult

logger = get_logger(__name__)


class ImplementationExecutor:
    """Executor for implementation tasks with iteration loop."""

    def __init__(
        self,
        project_id: str,
        repo_path: Path | None = None,
    ):
        """Initialize executor.

        Args:
            project_id: Project ID
            repo_path: Path to git repository. If None, looks up from projects table.
        """
        self.project_id = project_id
        if repo_path:
            self.repo_path = repo_path
        else:
            from app.storage.projects import get_project_root_path

            root = get_project_root_path(project_id)
            if not root:
                raise ValueError(f"Project {project_id} not found or has no root_path")
            self.repo_path = Path(root)

    def start_execution(
        self,
        task_id: str,
        agent_type: str = "claude",
    ) -> str:
        """Start execution of a task.

        Creates a new agent session with initialized build_state.

        Args:
            task_id: Task ID to execute
            agent_type: Model type ('claude' or 'gemini')

        Returns:
            Session ID
        """
        task = task_store.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        build_state: dict[str, Any] = {
            "task_id": task_id,
            "status": "running",
            "completed_tasks": [],
            "current_task_id": None,
            "current_phase": "implement",
            "iteration": 0,
            "pre_merge_sha": None,
            "started_at": datetime.now(UTC).isoformat(),
        }

        task_store.update_task(task_id, current_phase="implement")

        session = create_session(
            project_id=self.project_id,
            agent_type=agent_type,
            build_state=build_state,
        )

        session_id: str = session["session_id"]
        logger.info(
            "execution_started",
            task_id=task_id,
            session_id=session_id,
        )

        return session_id

    def execute_next_task(
        self,
        session_id: str,
        max_iterations: int = 5,
        is_manual_execution: bool = False,
    ) -> ExecutionResult:
        """Execute the next task in the plan with iteration loop.

        Args:
            session_id: Session ID from start_execution
            max_iterations: Maximum iterations before giving up
            is_manual_execution: True when called via API or CC session,
                                 False when called by autonomous pickup.

        Returns:
            ExecutionResult with success status and details
        """
        session = get_session(self.project_id, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        build_state = session.get("build_state") or {}

        task_id = session.get("context", {}).get("task_id") or build_state.get("task_id")
        if not task_id:
            raise ValueError("No task_id found in session")

        task = task_store.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        completed = set(build_state.get("completed_tasks", []))
        current_task = get_next_task_from_subtasks(task_id, completed)

        if current_task:
            logger.info(
                "using_subtasks_table",
                task_id=task_id,
                subtask_id=current_task.get("id"),
            )
        else:
            return ExecutionResult(
                success=True,
                iterations=0,
                model_used="none",
                reason="all_tasks_complete",
            )

        build_state["using_subtasks_table"] = True
        build_state["current_subtask_id"] = current_task.get("subtask_full_id")

        # Check for standalone task handling
        capability_id = task.get("capability_id")
        labels = list(task.get("labels") or [])
        is_auto_generated = "auto-generated" in labels
        is_standalone = not capability_id

        if is_standalone and not is_auto_generated and not is_manual_execution:
            logger.warning(
                "standalone_task_rejected",
                task_id=task_id,
                reason="Standalone tasks require manual execution",
            )
            return ExecutionResult(
                success=False,
                iterations=0,
                model_used="none",
                reason="standalone_requires_manual",
                error="Standalone tasks require manual execution",
            )

        if is_standalone and is_manual_execution:
            logger.warning(
                "executing_standalone_task",
                task_id=task_id,
                message="Executing standalone task - no capability verification available",
            )

        if is_standalone:
            capability_id = "general"

        from ..git_service import get_current_commit

        if not build_state.get("pre_merge_sha"):
            build_state["pre_merge_sha"] = get_current_commit(self.repo_path)

        build_state["current_task_id"] = current_task.get("id")
        self._update_build_state(session_id, build_state)

        files = current_task.get("files_affected") or task.get("files_affected") or []

        return run_iteration_loop(
            project_id=self.project_id,
            repo_path=self.repo_path,
            session_id=session_id,
            task_id=task_id,
            task=task,
            current_task=current_task,
            build_state=build_state,
            completed=completed,
            files=files,
            capability_id=capability_id or "general",
            max_iterations=max_iterations,
            update_phase_callback=self._update_phase,
        )

    def resume_execution(self, session_id: str) -> str:
        """Resume execution from an existing session."""
        session = get_session(self.project_id, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        build_state = session.get("build_state") or {}
        build_state["status"] = "running"
        self._update_build_state(session_id, build_state)

        return session_id

    def _update_build_state(self, session_id: str, build_state: dict[str, Any]) -> None:
        """Update build_state in session."""
        update_session(self.project_id, session_id, build_state=build_state)

    def _update_phase(self, task_id: str, phase: str, build_state: dict[str, Any]) -> None:
        """Update task phase based on execution progress."""
        build_state["current_phase"] = phase
        task_store.update_task(task_id, current_phase=phase)
        logger.info("phase_updated", task_id=task_id, phase=phase)
