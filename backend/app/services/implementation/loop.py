"""Implementation iteration loop logic.

Separated from executor.py to reduce file size.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.agent_sessions import update_session
from ..autonomous.prompt_builder import build_execution_prompt
from ..autonomous.tier_classifier import classify_tier, select_model_for_tier
from ..git_service import commit_changes, revert_to
from .agent import consult_alternate, execute_agent, parse_and_apply_changes
from .context import build_context
from .subtasks import mark_subtask_complete
from .types import ExecutionResult
from .verification import (
    check_step_completion,
    compute_error_signature,
    run_verification,
)

logger = get_logger(__name__)


def run_iteration_loop(
    project_id: str,
    repo_path: Path,
    session_id: str,
    task_id: str,
    task: dict[str, Any],
    current_task: dict[str, Any],
    build_state: dict[str, Any],
    completed: set[str],
    files: list[str],
    capability_id: int | str,
    max_iterations: int,
    update_phase_callback: Callable[[str, str, dict[str, Any]], None],
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

    context = build_context(project_id, files)

    models_tried: list[str] = []
    consecutive_identical_errors = 0
    last_error_signature: str | None = None
    iteration_context: dict[str, Any] | None = None

    was_consulted = False
    was_handoff = False
    execution_start = datetime.now(UTC)

    for iteration in range(1, max_iterations + 1):
        build_state["iteration"] = iteration
        update_session(project_id, session_id, build_state=build_state)

        current_model, was_consulted, was_handoff, iteration_context = _select_model(
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
            output = execute_agent(current_model, prompt, repo_path)
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

        if not output or not parse_and_apply_changes(output, repo_path):
            iteration_context = {
                "test_failures": "No valid code changes in output",
                "static_failures": "",
            }
            consecutive_identical_errors += 1
            continue

        try:
            commit_changes(
                f"Task {current_task.get('id')} - iteration {iteration}",
                repo_path,
            )
        except Exception as e:
            iteration_context = {
                "test_failures": f"Git commit failed: {e}",
                "static_failures": "",
            }
            continue

        update_phase_callback(task_id, "test", build_state)
        test_result = run_verification(repo_path, files, capability_id)

        if test_result["success"]:
            return _handle_success(
                project_id=project_id,
                repo_path=repo_path,
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
                update_phase_callback=update_phase_callback,
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

    return _handle_exhaustion(
        repo_path=repo_path,
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


def _handle_success(
    project_id: str,
    repo_path: Path,
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
    update_phase_callback: Callable[[str, str, dict[str, Any]], None],
) -> ExecutionResult:
    """Handle successful task completion."""
    task_id_to_add = current_task.get("id") or ""
    completed.add(task_id_to_add)
    build_state["completed_tasks"] = list(completed)
    update_session(project_id, session_id, build_state=build_state)

    if build_state.get("using_subtasks_table"):
        mark_subtask_complete(current_task, str(repo_path), project_id=project_id)

    update_phase_callback(task_id, "verify", build_state)
    step_check = check_step_completion(project_id, task)

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
        update_phase_callback(task_id, "complete", build_state)
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


def _handle_exhaustion(
    repo_path: Path,
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
            revert_to(repo_path, pre_merge_sha)
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
        test_output=(iteration_context.get("test_failures") if iteration_context else None),
    )
