"""Implementation executor - Main executor class and iteration loop.

Provides the core execution engine for running tasks with:
- Iteration loop (up to max_iterations)
- External verification (pytest, pyright, ruff)
- Alternate model consultation on thrashing
- Rollback on exhaustion
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.agent_sessions import create_session, get_session, update_session
from ...storage.steps import update_step_passes
from ...storage.subtasks import update_subtask_passes
from ..autonomous.prompt_builder import build_execution_prompt
from ..autonomous.tier_classifier import classify_tier, select_model_for_tier
from ..git_service import commit_changes, get_current_commit, revert_to
from .agent import consult_alternate, execute_agent, parse_and_apply_changes
from .context import build_context
from .subtasks import get_next_task_from_subtasks
from .types import ExecutionResult
from .verification import check_step_completion, compute_error_signature, run_verification

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
            is_manual_execution: True when called via /do_it or API,
                                 False when called by Celery autonomous pickup.

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
                reason="Standalone tasks require manual execution via /do_it",
            )
            return ExecutionResult(
                success=False,
                iterations=0,
                model_used="none",
                reason="standalone_requires_manual",
                error="Standalone tasks require manual execution via /do_it",
            )

        if is_standalone and is_manual_execution:
            logger.warning(
                "executing_standalone_task",
                task_id=task_id,
                message="Executing standalone task - no capability verification available",
            )

        if is_standalone:
            capability_id = "general"

        if not build_state.get("pre_merge_sha"):
            build_state["pre_merge_sha"] = get_current_commit(self.repo_path)

        build_state["current_task_id"] = current_task.get("id")
        self._update_build_state(session_id, build_state)

        files = current_task.get("files_affected") or task.get("files_affected") or []

        return self._run_iteration_loop(
            session_id=session_id,
            task_id=task_id,
            task=task,
            current_task=current_task,
            build_state=build_state,
            completed=completed,
            files=files,
            capability_id=capability_id or "general",
            max_iterations=max_iterations,
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

    def _run_iteration_loop(
        self,
        session_id: str,
        task_id: str,
        task: dict[str, Any],
        current_task: dict[str, Any],
        build_state: dict[str, Any],
        completed: set[str],
        files: list[str],
        capability_id: int | str,
        max_iterations: int,
    ) -> ExecutionResult:
        """Run the main iteration loop for task execution."""
        tier_info = {
            "complexity": len(files) * 5,
            "lines": 300,
            "files_count": len(files),
        }
        tier = classify_tier(tier_info)
        primary_model = select_model_for_tier(tier, manual=True)
        alternate_model = select_model_for_tier(tier + 1 if tier < 4 else 4)

        context = build_context(self.project_id, files)

        models_tried: list[str] = []
        consecutive_identical_errors = 0
        last_error_signature: str | None = None
        iteration_context: dict[str, Any] | None = None

        was_consulted = False
        was_handoff = False
        execution_start = datetime.now(UTC)

        for iteration in range(1, max_iterations + 1):
            build_state["iteration"] = iteration
            self._update_build_state(session_id, build_state)

            current_model, was_consulted, was_handoff, iteration_context = self._select_model(
                iteration=iteration,
                consecutive_identical_errors=consecutive_identical_errors,
                primary_model=primary_model,  # type: ignore[arg-type]
                alternate_model=alternate_model,  # type: ignore[arg-type]
                current_task=current_task,
                iteration_context=iteration_context,
                was_consulted=was_consulted,
                was_handoff=was_handoff,
            )

            model_name = f"{current_model['provider']}/{current_model['model']}"
            if model_name not in models_tried:
                models_tried.append(model_name)

            if iteration_context:
                iteration_context["iteration"] = iteration

            prompt = build_execution_prompt(
                {**task, "files_affected": files},
                context,
                iteration_context,
            )

            try:
                output = execute_agent(current_model, prompt, self.repo_path)
            except TimeoutError:
                iteration_context = {
                    "test_failures": "Agent execution timed out",
                    "static_failures": "",
                }
                continue
            except Exception as e:
                iteration_context = {"test_failures": f"Agent error: {e}", "static_failures": ""}
                continue

            if not output or not parse_and_apply_changes(output, self.repo_path, False):
                iteration_context = {
                    "test_failures": "No valid code changes in output",
                    "static_failures": "",
                }
                consecutive_identical_errors += 1
                continue

            try:
                self._commit_changes(task_id, current_task, iteration)
            except Exception as e:
                iteration_context = {
                    "test_failures": f"Git commit failed: {e}",
                    "static_failures": "",
                }
                continue

            self._update_phase(task_id, "test", build_state)
            test_result = run_verification(self.repo_path, files, capability_id)

            if test_result["success"]:
                return self._handle_success(
                    session_id=session_id,
                    task_id=task_id,
                    task=task,
                    current_task=current_task,
                    build_state=build_state,
                    completed=completed,
                    iteration=iteration,
                    model_name=model_name,
                    models_tried=models_tried,
                    was_consulted=was_consulted,
                    was_handoff=was_handoff,
                    execution_start=execution_start,
                    test_result=test_result,
                )

            error_sig = compute_error_signature(test_result.get("output", ""))
            if error_sig == last_error_signature:
                consecutive_identical_errors += 1
            else:
                consecutive_identical_errors = 0
                last_error_signature = error_sig

            iteration_context = {
                "test_failures": test_result.get("pytest_output", ""),
                "static_failures": test_result.get("static_output", ""),
            }

        return self._handle_exhaustion(
            task_id=task_id,
            build_state=build_state,
            max_iterations=max_iterations,
            models_tried=models_tried,
            was_consulted=was_consulted,
            was_handoff=was_handoff,
            execution_start=execution_start,
            iteration_context=iteration_context,
        )

    def _select_model(
        self,
        iteration: int,
        consecutive_identical_errors: int,
        primary_model: dict[str, Any],
        alternate_model: dict[str, Any],
        current_task: dict[str, Any],
        iteration_context: dict[str, Any] | None,
        was_consulted: bool,
        was_handoff: bool,
    ) -> tuple[dict[str, Any], bool, bool, dict[str, Any] | None]:
        """Select model based on thrashing detection."""
        if consecutive_identical_errors >= 2 and iteration >= 3:
            if iteration == 5:
                was_handoff = True
                if iteration_context:
                    iteration_context["handoff_context"] = (
                        f"Failed after {iteration - 1} attempts with errors:\n"
                        f"{iteration_context.get('test_failures', '')}"
                    )
                return alternate_model, was_consulted, was_handoff, iteration_context
            else:
                was_consulted = True
                advice = consult_alternate(
                    alternate_model,
                    current_task,
                    iteration_context.get("test_failures", "") if iteration_context else "",
                )
                if iteration_context:
                    iteration_context["advice"] = advice
                return primary_model, was_consulted, was_handoff, iteration_context

        return primary_model, was_consulted, was_handoff, iteration_context

    def _commit_changes(self, task_id: str, current_task: dict[str, Any], iteration: int) -> None:
        """Commit changes in repo."""
        commit_changes(
            f"Task {current_task.get('id')} - iteration {iteration}",
            self.repo_path,
        )

    def _handle_success(
        self,
        session_id: str,
        task_id: str,
        task: dict[str, Any],
        current_task: dict[str, Any],
        build_state: dict[str, Any],
        completed: set[str],
        iteration: int,
        model_name: str,
        models_tried: list[str],
        was_consulted: bool,
        was_handoff: bool,
        execution_start: datetime,
        test_result: dict[str, Any],
    ) -> ExecutionResult:
        """Handle successful task completion."""
        task_id_to_add = current_task.get("id") or ""
        completed.add(task_id_to_add)
        build_state["completed_tasks"] = list(completed)
        self._update_build_state(session_id, build_state)

        if build_state.get("using_subtasks_table"):
            self._mark_subtask_complete(current_task)

        self._update_phase(task_id, "verify", build_state)
        step_check = check_step_completion(self.project_id, task)

        execution_time = (datetime.now(UTC) - execution_start).total_seconds()
        task_store.update_task(
            task_id,
            review_result={
                "iterations": iteration,
                "model_used": model_name,
                "models_tried": models_tried,
                "consulted": was_consulted,
                "handoff": was_handoff,
                "reason": "success",
                "execution_time_seconds": round(execution_time, 2),
                "steps_verified": step_check["verified_count"],
                "steps_total": step_check["total"],
                "unverified_steps": step_check["unverified"],
            },
        )

        if step_check["all_verified"]:
            self._update_phase(task_id, "complete", build_state)
            task_store.update_task_status(task_id, "completed")
            logger.info("task_completed", task_id=task_id)
        else:
            logger.warning(
                "steps_not_verified",
                task_id=task_id,
                unverified=step_check["unverified"],
            )

        return ExecutionResult(
            success=True,
            iterations=iteration,
            model_used=model_name,
            models_tried=models_tried,
            test_output=test_result.get("output"),
        )

    def _mark_subtask_complete(self, current_task: dict[str, Any]) -> None:
        """Mark subtask and its steps as complete."""
        subtask_full_id = current_task.get("subtask_full_id")
        if not subtask_full_id:
            return

        steps = current_task.get("steps") or []
        for step in steps:
            step_number = step.get("step_number")
            if step_number and not step.get("passes"):
                update_step_passes(
                    subtask_full_id,
                    step_number,
                    True,
                    project_root=str(self.repo_path),
                )
                logger.debug(
                    "step_marked_complete",
                    subtask_id=subtask_full_id,
                    step_number=step_number,
                )

        match = re.match(r"^(.+)-(\d+\.\d+)$", subtask_full_id)
        if match:
            parsed_task_id, parsed_subtask_id = match.groups()
            update_subtask_passes(parsed_task_id, parsed_subtask_id, True)
            logger.info(
                "subtask_marked_complete",
                subtask_id=parsed_subtask_id,
                task_id=parsed_task_id,
            )
        else:
            logger.error("invalid_subtask_full_id_format", subtask_full_id=subtask_full_id)

    def _handle_exhaustion(
        self,
        task_id: str,
        build_state: dict[str, Any],
        max_iterations: int,
        models_tried: list[str],
        was_consulted: bool,
        was_handoff: bool,
        execution_start: datetime,
        iteration_context: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Handle iteration exhaustion."""
        pre_merge_sha = build_state.get("pre_merge_sha")
        if pre_merge_sha:
            try:
                revert_to(self.repo_path, pre_merge_sha)
                logger.info("reverted_after_exhaustion", sha=pre_merge_sha[:8])
            except Exception as e:
                logger.error("revert_failed", error=str(e))

        execution_time = (datetime.now(UTC) - execution_start).total_seconds()
        task_store.update_task(
            task_id,
            review_result={
                "iterations": max_iterations,
                "model_used": models_tried[-1] if models_tried else "none",
                "models_tried": models_tried,
                "consulted": was_consulted,
                "handoff": was_handoff,
                "reason": "exhausted",
                "execution_time_seconds": round(execution_time, 2),
                "last_error": (
                    iteration_context.get("test_failures", "")[:500] if iteration_context else None
                ),
            },
        )

        return ExecutionResult(
            success=False,
            iterations=max_iterations,
            model_used=models_tried[-1] if models_tried else "none",
            models_tried=models_tried,
            reason="exhausted",
            error=f"Failed after {max_iterations} iterations",
            test_output=iteration_context.get("test_failures") if iteration_context else None,
        )

    def _update_build_state(self, session_id: str, build_state: dict[str, Any]) -> None:
        """Update build_state in session."""
        update_session(self.project_id, session_id, build_state=build_state)

    def _update_phase(self, task_id: str, phase: str, build_state: dict[str, Any]) -> None:
        """Update task phase based on execution progress."""
        build_state["current_phase"] = phase
        task_store.update_task(task_id, current_phase=phase)
        logger.info("phase_updated", task_id=task_id, phase=phase)
