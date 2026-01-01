"""Implementation executor service for autonomous task execution.

Provides the core execution engine for running tasks with:
- Iteration loop (up to max_iterations)
- External verification (pytest, pyright, ruff)
- Alternate model consultation on thrashing
- Rollback on exhaustion
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_GEMINI_MODEL, GEMINI_PRO
from ..logging_config import get_logger
from ..storage import tasks as task_store
from ..storage.agent_sessions import create_session, get_session, update_session
from ..storage.connection import get_connection
from ..storage.criteria import get_effective_criteria
from ..storage.steps import update_step_passes
from ..storage.subtasks import get_subtasks_for_task, update_subtask_passes
from .agents import get_agent
from .autonomous.prompt_builder import build_execution_prompt
from .autonomous.tier_classifier import classify_tier, select_model_for_tier
from .context_helpers import (
    filter_rules_by_files,
    get_observations_for_files,
    get_patterns_for_files,
)
from .git_service import commit_changes, get_current_commit, revert_to
from .worktree_manager import WorktreeManager, get_worktree_manager

logger = get_logger(__name__)

# Default repository path
DEFAULT_REPO_PATH = Path("/home/kasadis/summitflow")

# Timeouts
AGENT_TIMEOUT_SECONDS = 300  # 5 minutes
SUBPROCESS_TIMEOUT_SECONDS = 120  # 2 minutes


@dataclass
class ExecutionResult:
    """Result of task execution."""

    success: bool
    iterations: int
    model_used: str
    models_tried: list[str] = field(default_factory=list)
    reason: str | None = None
    test_output: str | None = None
    error: str | None = None


class ImplementationExecutor:
    """Executor for implementation tasks with iteration loop."""

    def __init__(
        self,
        project_id: str,
        repo_path: Path | None = None,
        use_worktree: bool = False,
    ):
        """Initialize executor.

        Args:
            project_id: Project ID
            repo_path: Path to git repository (default: ~/summitflow)
            use_worktree: If True, execute tasks in isolated git worktrees
        """
        self.project_id = project_id
        self.repo_path = repo_path or DEFAULT_REPO_PATH
        self.use_worktree = use_worktree
        self._worktree_manager: WorktreeManager | None = None
        self._current_worktree_path: Path | None = None

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

    def start_execution(
        self,
        task_id: str,
        agent_type: str = "claude",
    ) -> str:
        """Start execution of a task.

        Creates a new agent session with initialized build_state.
        If use_worktree=True, creates an isolated worktree for the task.

        Args:
            task_id: Task ID to execute
            agent_type: Model type ('claude' or 'gemini')

        Returns:
            Session ID
        """
        # Get task
        task = task_store.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Initialize build_state
        build_state: dict[str, Any] = {
            "task_id": task_id,  # Store task_id for execute_next_task to find
            "status": "running",
            "completed_tasks": [],
            "current_task_id": None,
            "current_phase": "implement",  # Phase: plan → implement → test → verify → complete
            "iteration": 0,
            "pre_merge_sha": None,
            "started_at": datetime.now(UTC).isoformat(),
            "worktree_enabled": self.use_worktree,
            "worktree_path": None,
        }

        # Create worktree if enabled
        if self.use_worktree:
            worktree_info = self.worktree_manager.create_worktree(self.project_id, task_id)
            self._current_worktree_path = worktree_info.path
            build_state["worktree_path"] = str(worktree_info.path)
            build_state["worktree_branch"] = worktree_info.branch
            logger.info(
                "worktree_initialized",
                task_id=task_id,
                path=str(worktree_info.path),
                branch=worktree_info.branch,
            )

        # Update task current_phase
        task_store.update_task(task_id, current_phase="implement")

        # Create session
        session = create_session(
            project_id=self.project_id,
            agent_type=agent_type,
            build_state=build_state,
        )

        logger.info(
            "execution_started",
            task_id=task_id,
            session_id=session["session_id"],
            worktree=build_state.get("worktree_path"),
        )

        return session["session_id"]

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
                                 Standalone tasks (no capability_id) require manual execution.

        Returns:
            ExecutionResult with success status and details
        """
        # Load session
        session = get_session(self.project_id, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        build_state = session.get("build_state") or {}

        # Restore worktree path from build_state if resuming
        if build_state.get("worktree_enabled") and build_state.get("worktree_path"):
            self._current_worktree_path = Path(build_state["worktree_path"])
            self.use_worktree = True
            logger.info(
                "worktree_restored",
                path=str(self._current_worktree_path),
                exists=self._current_worktree_path.exists(),
            )

        # Get task from session context or build_state
        task_id = session.get("context", {}).get("task_id") or build_state.get("task_id")
        if not task_id:
            # Try to find from recent tasks
            raise ValueError("No task_id found in session")

        task = task_store.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Track whether we're using subtasks table or plan_content
        using_subtasks_table = False
        completed = set(build_state.get("completed_tasks", []))

        # Try subtasks table first (normalized storage)
        current_task = self._get_next_task_from_subtasks(task_id, completed)
        if current_task:
            using_subtasks_table = True
            logger.info(
                "using_subtasks_table",
                task_id=task_id,
                subtask_id=current_task.get("id"),
            )
        else:
            # Fallback to plan_content (legacy storage)
            plan = task.get("plan_content") or {}
            tasks_list = plan.get("tasks", []) if isinstance(plan, dict) else []

            for t in tasks_list:
                if t.get("id") not in completed and not t.get("passes", False):
                    current_task = t
                    break

            if current_task:
                logger.info(
                    "using_plan_content",
                    task_id=task_id,
                    subtask_id=current_task.get("id"),
                )

        if not current_task:
            return ExecutionResult(
                success=True,
                iterations=0,
                model_used="none",
                reason="all_tasks_complete",
            )

        # Store source type in build_state for step tracking
        build_state["using_subtasks_table"] = using_subtasks_table
        if using_subtasks_table:
            build_state["current_subtask_id"] = current_task.get("subtask_full_id")

        plan = task.get("plan_content") or {}

        # Check for capability_id (optional for auto-generated tasks)
        capability_id = task.get("capability_id") or (
            plan.get("context", {}).get("capability_id") if isinstance(plan, dict) else None
        )

        labels = list(task.get("labels") or [])
        is_auto_generated = "auto-generated" in labels
        is_standalone = not capability_id

        # Standalone task handling
        if is_standalone and not is_auto_generated:
            if not is_manual_execution:
                # Autonomous pickup should not execute standalone tasks
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
            else:
                # Manual execution of standalone task - log warning and continue
                logger.warning(
                    "executing_standalone_task",
                    task_id=task_id,
                    message="Executing standalone task - no capability verification available",
                )

        # For auto-generated tasks without capability_id, use general verification
        if is_standalone:
            capability_id = "general"  # Sentinel for general verification

        # Capture pre_merge_sha once at task start (from main repo, not worktree)
        if not build_state.get("pre_merge_sha"):
            build_state["pre_merge_sha"] = get_current_commit(self.repo_path)

        build_state["current_task_id"] = current_task.get("id")
        self._update_build_state(session_id, build_state)

        # Get affected files
        files = current_task.get("files_affected") or task.get("files_affected") or []

        # Classify tier and select models
        tier_info = {
            "complexity": len(files) * 5,  # Rough estimate
            "lines": 300,  # Default
            "files_count": len(files),
        }
        tier = classify_tier(tier_info)
        primary_model = select_model_for_tier(tier, manual=session.get("agent_type") == "claude")
        alternate_model = select_model_for_tier(tier + 1 if tier < 4 else 4)

        # Build context
        context = self._build_context(files)

        # Iteration loop
        models_tried = []
        consecutive_identical_errors = 0
        last_error_signature = None
        iteration_context: dict[str, Any] | None = None

        # Observability: Track consultation and handoff for metrics
        was_consulted = False
        was_handoff = False
        execution_start = datetime.now(UTC)

        for iteration in range(1, max_iterations + 1):
            build_state["iteration"] = iteration
            self._update_build_state(session_id, build_state)

            # Determine current model based on thrashing
            if consecutive_identical_errors >= 2 and iteration >= 3:
                if iteration == 5:
                    # Full handoff
                    current_model = alternate_model
                    was_handoff = True  # Observability: Track handoff
                    if iteration_context:
                        iteration_context["handoff_context"] = (
                            f"Failed after {iteration - 1} attempts with errors:\n"
                            f"{iteration_context.get('test_failures', '')}"
                        )
                else:
                    # Consult alternate for advice
                    current_model = primary_model
                    was_consulted = True  # Observability: Track consultation
                    advice = self._consult_alternate(
                        alternate_model,
                        current_task,
                        iteration_context.get("test_failures", "") if iteration_context else "",
                    )
                    if iteration_context:
                        iteration_context["advice"] = advice
            else:
                current_model = primary_model

            model_name = f"{current_model['provider']}/{current_model['model']}"
            if model_name not in models_tried:
                models_tried.append(model_name)

            # Build prompt
            if iteration_context:
                iteration_context["iteration"] = iteration

            prompt = build_execution_prompt(
                {**task, "files_affected": files},
                context,
                iteration_context,
            )

            # Execute agent (placeholder - actual execution would use Claude/Gemini SDK)
            try:
                output = self._execute_agent(current_model, prompt)
            except TimeoutError:
                iteration_context = {
                    "test_failures": "Agent execution timed out",
                    "static_failures": "",
                }
                continue
            except Exception as e:
                iteration_context = {
                    "test_failures": f"Agent error: {e}",
                    "static_failures": "",
                }
                continue

            # Parse and apply changes
            if not output or not self._parse_and_apply_changes(output):
                iteration_context = {
                    "test_failures": "No valid code changes in output",
                    "static_failures": "",
                }
                consecutive_identical_errors += 1
                continue

            # Commit changes (in worktree if enabled, otherwise main repo)
            try:
                if self.use_worktree and self._current_worktree_path:
                    self.worktree_manager.commit_in_worktree(
                        self.project_id,
                        task_id,
                        f"Task {current_task.get('id')} - iteration {iteration}",
                    )
                else:
                    commit_changes(
                        f"Task {current_task.get('id')} - iteration {iteration}",
                        self.repo_path,
                    )
            except Exception as e:
                iteration_context = {
                    "test_failures": f"Git commit failed: {e}",
                    "static_failures": "",
                }
                continue

            # Run external verification - update phase to "test"
            self._update_phase(task_id, "test", build_state)
            test_result = self._run_verification(files, capability_id)

            if test_result["success"]:
                # Mark task complete in build_state
                completed.add(current_task.get("id"))
                build_state["completed_tasks"] = list(completed)
                self._update_build_state(session_id, build_state)

                # If using subtasks table, mark steps and subtask as complete
                if build_state.get("using_subtasks_table"):
                    subtask_full_id = current_task.get("subtask_full_id")
                    if subtask_full_id:
                        # Mark all steps as passed
                        steps = current_task.get("steps_from_table") or []
                        for step in steps:
                            step_number = step.get("step_number")
                            if step_number and not step.get("passes"):
                                update_step_passes(subtask_full_id, step_number, True)
                                logger.debug(
                                    "step_marked_complete",
                                    subtask_id=subtask_full_id,
                                    step_number=step_number,
                                )
                        # Mark subtask as passed
                        update_subtask_passes(subtask_full_id, True)
                        logger.info(
                            "subtask_marked_complete",
                            subtask_id=subtask_full_id,
                            task_id=task_id,
                        )

                # Check acceptance criteria - update phase to "verify"
                self._update_phase(task_id, "verify", build_state)
                criteria_check = self._check_acceptance_criteria(task_id)

                # Observability: Store execution metrics in review_result
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
                        "criteria_verified": criteria_check["verified_count"],
                        "criteria_total": criteria_check["total"],
                        "unverified_criteria": criteria_check["unverified"],
                    },
                )

                # Update phase to complete if all criteria verified
                if criteria_check["all_verified"]:
                    self._update_phase(task_id, "complete", build_state)
                    # Set task status to completed (syncs phase and clears claims)
                    task_store.update_task_status(task_id, "completed")
                    logger.info("task_completed", task_id=task_id)
                else:
                    logger.warning(
                        "criteria_not_verified",
                        task_id=task_id,
                        unverified=criteria_check["unverified"],
                    )

                return ExecutionResult(
                    success=True,
                    iterations=iteration,
                    model_used=model_name,
                    models_tried=models_tried,
                    test_output=test_result.get("output"),
                )

            # Compute error signature
            error_sig = self._compute_error_signature(test_result.get("output", ""))
            if error_sig == last_error_signature:
                consecutive_identical_errors += 1
            else:
                consecutive_identical_errors = 0
                last_error_signature = error_sig

            # Build iteration context for next attempt
            iteration_context = {
                "test_failures": test_result.get("pytest_output", ""),
                "static_failures": test_result.get("static_output", ""),
            }

        # All iterations exhausted - revert
        pre_merge_sha = build_state.get("pre_merge_sha")
        if pre_merge_sha:
            try:
                revert_to(self.repo_path, pre_merge_sha)
                logger.info("reverted_after_exhaustion", sha=pre_merge_sha[:8])
            except Exception as e:
                logger.error("revert_failed", error=str(e))

        # Observability: Store execution metrics for exhausted case
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

    def resume_execution(self, session_id: str) -> str:
        """Resume execution from an existing session.

        Args:
            session_id: Session ID to resume

        Returns:
            Session ID (same as input)
        """
        session = get_session(self.project_id, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        build_state = session.get("build_state") or {}
        build_state["status"] = "running"
        self._update_build_state(session_id, build_state)

        return session_id

    def _build_context(self, files: list[str]) -> dict[str, Any]:
        """Build context for a task based on affected files."""
        rules = filter_rules_by_files(files)

        # Read rule contents
        rule_contents: dict[str, str] = {}
        for rule in rules:
            for rules_dir in [
                Path("/home/kasadis/summitflow/.claude/rules"),
                Path("/home/kasadis/.claude/rules"),
            ]:
                rule_path = rules_dir / rule
                if rule_path.exists():
                    rule_contents[rule] = rule_path.read_text()
                    break

        patterns = get_patterns_for_files(self.project_id, files)
        observations = get_observations_for_files(self.project_id, files)

        return {
            "files": files,
            "rules": rules,
            "rule_contents": rule_contents,
            "patterns": patterns,
            "observations": observations,
        }

    def _get_next_task_from_subtasks(
        self, task_id: str, completed_subtasks: set[str]
    ) -> dict[str, Any] | None:
        """Get the next incomplete subtask from the task_subtasks table.

        Args:
            task_id: Parent task ID
            completed_subtasks: Set of completed subtask IDs (format: "{subtask_id}")

        Returns:
            Dict with subtask info including steps, or None if all complete.
            Returns dict with keys: id, subtask_id, description, phase, steps
        """
        subtasks = get_subtasks_for_task(task_id, include_steps=True)
        if not subtasks:
            return None

        for subtask in subtasks:
            subtask_id = subtask.get("subtask_id", "")
            # Check if subtask is complete (either passes=True or in completed set)
            if subtask.get("passes"):
                continue
            if subtask_id in completed_subtasks:
                continue

            # Found incomplete subtask - get its steps
            full_id = subtask.get("id", "")  # e.g., "task-abc123-1.1"
            steps = subtask.get("steps_from_table") or []

            # Convert to execution format compatible with plan_content tasks
            return {
                "id": subtask_id,
                "subtask_full_id": full_id,
                "description": subtask.get("description", ""),
                "phase": subtask.get("phase", ""),
                "steps": [s.get("description", "") for s in steps],
                "steps_from_table": steps,  # Keep full step objects for tracking
                "display_order": subtask.get("display_order", 0),
            }

        return None

    def _update_build_state(self, session_id: str, build_state: dict[str, Any]) -> None:
        """Update build_state in session."""
        update_session(self.project_id, session_id, build_state=build_state)

    def _update_phase(self, task_id: str, phase: str, build_state: dict[str, Any]) -> None:
        """Update task phase based on execution progress.

        Phase values:
        - plan: Task has plan_content, not started
        - implement: Executing subtasks
        - test: Running verification tests
        - verify: Checking acceptance criteria
        - complete: All done

        Args:
            task_id: Task ID
            phase: New phase value
            build_state: Current build_state to update
        """
        build_state["current_phase"] = phase
        task_store.update_task(task_id, current_phase=phase)
        logger.info("phase_updated", task_id=task_id, phase=phase)

    def _check_acceptance_criteria(self, task_id: str) -> dict[str, Any]:
        """Check if all acceptance criteria are verified.

        Uses get_effective_criteria to source from capability or task junction
        tables, with JSONB fallback for backward compatibility.

        Args:
            task_id: Task ID

        Returns:
            Dict with:
            - all_verified: bool
            - total: int
            - verified_count: int
            - unverified: list of criterion IDs
        """
        task = task_store.get_task(task_id)
        if not task:
            return {"all_verified": True, "total": 0, "verified_count": 0, "unverified": []}

        # Use get_effective_criteria for dual-source support
        with get_connection() as conn:
            criteria = get_effective_criteria(conn, self.project_id, task)

        if not criteria:
            return {"all_verified": True, "total": 0, "verified_count": 0, "unverified": []}

        verified_count = sum(1 for c in criteria if c.get("verified"))
        unverified = [c.get("criterion_id") for c in criteria if not c.get("verified")]

        return {
            "all_verified": len(unverified) == 0,
            "total": len(criteria),
            "verified_count": verified_count,
            "unverified": unverified,
        }

    def _execute_agent(self, model: Any, prompt: str) -> str:
        """Execute agent with model and prompt.

        Args:
            model: ModelConfig dict with provider, model, max_tokens, description
            prompt: The execution prompt built by prompt_builder

        Returns:
            Agent response text (should contain ```file:path``` blocks)
        """
        provider = model.get("provider", "gemini")
        model_id = model.get("model", DEFAULT_GEMINI_MODEL)
        max_tokens = model.get("max_tokens", 8192)

        logger.info(
            "agent_execution_start",
            provider=provider,
            model=model_id,
            prompt_len=len(prompt),
        )

        try:
            agent = get_agent(provider, model_id)

            # Use working_dir for Claude to enable file operations
            # When worktree is enabled, use worktree path for isolation
            working_dir = str(self.effective_repo_path) if provider == "claude" else None

            response = agent.generate(
                prompt=prompt,
                system="You are an expert software engineer implementing code changes. Output only valid code changes in the specified format.",
                max_tokens=max_tokens,
                temperature=0.7,
                working_dir=working_dir,
            )

            logger.info(
                "agent_execution_complete",
                provider=provider,
                model=model_id,
                response_len=len(response.content),
                tokens_used=response.usage.get("total_tokens", 0) if response.usage else 0,
            )

            return response.content

        except Exception as e:
            logger.error(
                "agent_execution_failed",
                provider=provider,
                model=model_id,
                error=str(e),
            )
            raise

    def _parse_and_apply_changes(self, output: str) -> bool:
        """Parse agent output and apply file changes.

        Expected format:
        ```file:path/to/file.py
        file contents
        ```

        Returns:
            True if changes were applied, False otherwise
        """
        pattern = r"```file:([^\n]+)\n(.*?)```"
        matches = re.findall(pattern, output, re.DOTALL)

        if not matches:
            return False

        for file_path, content in matches:
            file_path = file_path.strip()
            # Use effective_repo_path for worktree isolation
            full_path = self.effective_repo_path / file_path

            # Create parent directories if needed
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            full_path.write_text(content.strip() + "\n")
            logger.info("file_written", path=file_path, in_worktree=self.use_worktree)

        return True

    def _run_verification(
        self,
        files: list[str],
        capability_id: int | str,
    ) -> dict[str, Any]:
        """Run external verification (pytest, pyright, ruff).

        Returns:
            Dict with success, output, pytest_output, static_output
        """
        result: dict[str, Any] = {
            "success": False,
            "output": "",
            "pytest_output": "",
            "static_output": "",
        }

        # Use effective_repo_path for worktree isolation
        backend_path = self.effective_repo_path / "backend"

        # Run pytest
        try:
            pytest_result = subprocess.run(
                [".venv/bin/pytest", "-v", "--tb=short"],
                cwd=backend_path,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            result["pytest_output"] = pytest_result.stdout + pytest_result.stderr
            pytest_passed = pytest_result.returncode == 0
        except subprocess.TimeoutExpired:
            result["pytest_output"] = "pytest timed out"
            pytest_passed = False
        except Exception as e:
            result["pytest_output"] = f"pytest error: {e}"
            pytest_passed = False

        # Run pyright
        try:
            pyright_result = subprocess.run(
                [".venv/bin/pyright", "app/"],
                cwd=backend_path,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            pyright_passed = pyright_result.returncode == 0
            result["static_output"] += f"pyright:\n{pyright_result.stdout}\n"
        except subprocess.TimeoutExpired:
            result["static_output"] += "pyright timed out\n"
            pyright_passed = False
        except Exception as e:
            result["static_output"] += f"pyright error: {e}\n"
            pyright_passed = False

        # Run ruff
        try:
            ruff_result = subprocess.run(
                [".venv/bin/ruff", "check", "app/"],
                cwd=backend_path,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            ruff_passed = ruff_result.returncode == 0
            result["static_output"] += f"ruff:\n{ruff_result.stdout}\n"
        except subprocess.TimeoutExpired:
            result["static_output"] += "ruff timed out\n"
            ruff_passed = False
        except Exception as e:
            result["static_output"] += f"ruff error: {e}\n"
            ruff_passed = False

        result["success"] = pytest_passed and pyright_passed and ruff_passed
        result["output"] = result["pytest_output"] + result["static_output"]

        return result

    def _compute_error_signature(self, error_output: str) -> str:
        """Compute a signature for error output to detect repeated failures."""
        # Extract just the error lines (ignore timing, counts)
        lines = []
        for line in error_output.split("\n"):
            if "FAILED" in line or "error:" in line.lower() or "Error" in line:
                lines.append(line.strip())

        signature_text = "\n".join(sorted(lines))
        return hashlib.md5(signature_text.encode()).hexdigest()

    def _consult_alternate(
        self,
        model: Any,
        task: dict[str, Any],
        error: str,
    ) -> str:
        """Consult alternate model for advice on fixing errors.

        When the primary model is thrashing (hitting same error repeatedly),
        we ask a different model for fresh perspective.

        Args:
            model: Current model config (we'll use the opposite provider)
            task: Task dict with title, description
            error: The repeated error message

        Returns:
            Advice string from alternate model
        """
        # Always use Gemini for consultation (Claude is primary for coding)
        # Gemini has large context window (1-2M) useful for analyzing errors
        alt_provider = "gemini"
        alt_model = GEMINI_PRO  # Pro for better reasoning

        logger.info(
            "consulting_alternate",
            primary_provider=model.get("provider", "claude"),
            alt_provider=alt_provider,
            error_len=len(error),
        )

        try:
            agent = get_agent(alt_provider, alt_model)  # type: ignore[arg-type]

            prompt = f"""A code implementation task is failing repeatedly with the same error.

Task: {task.get("title", "Unknown task")}
Description: {task.get("description", "No description")}

Repeated Error:
{error[:2000]}

Please analyze this error and provide specific, actionable advice to fix it.
Focus on:
1. Root cause of the error
2. Concrete steps to fix it
3. Any edge cases to consider

Keep response concise (under 500 words)."""

            response = agent.generate(
                prompt=prompt,
                system="You are a debugging expert. Provide clear, actionable advice.",
                max_tokens=1024,
                temperature=0.3,
            )

            logger.info(
                "alternate_consultation_complete",
                alt_provider=alt_provider,
                response_len=len(response.content),
            )

            return response.content

        except Exception as e:
            logger.warning(
                "alternate_consultation_failed",
                error=str(e),
            )
            return f"Consultation failed: {e}. Consider reviewing the error manually."
