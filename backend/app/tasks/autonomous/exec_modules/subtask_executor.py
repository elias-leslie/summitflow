"""Subtask execution with self-healing retry loop."""

from __future__ import annotations

import time
from typing import Any

from ....logging_config import get_logger
from .agent_execution import execute_agent_initial
from .agent_routing import get_agent_for_subtask
from .ah_events import emit_prompt_harness_snapshot
from .git_work_product import ensure_committed_work_product
from .interruption import ExecutionInterrupted
from .prompts import build_subtask_prompt_payload
from .result_processing import process_final_result
from .retry_loop import run_self_healing_loop
from .subtask_fallback import execute_with_fallbacks
from .subtask_helpers import handle_execution_error, initialize_subtask_logging
from .subtask_validation import validate_subtask_environment
from .worktree import get_project_path

logger = get_logger(__name__)


def _ensure_mergeable_work_product(
    task_id: str,
    subtask_short_id: str,
    project_path: str,
    project_id: str,
    all_passed: bool,
    step_results: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    """Commit verified work so canonical task closure can merge it."""
    if not all_passed:
        return all_passed, step_results

    commit_error = ensure_committed_work_product(
        task_id=task_id,
        subtask_short_id=subtask_short_id,
        project_path=project_path,
        project_id=project_id,
    )
    if not commit_error:
        return all_passed, step_results

    failed_result = {
        "step_number": 0,
        "passed": False,
        "output": commit_error,
        "reason": "commit_failed",
        "returncode": 1,
    }
    return False, [*step_results, failed_result]


def _setup_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
) -> tuple[str, str, str, Any]:
    """Initialize logging and validate the subtask environment.

    Returns (subtask_id, subtask_short_id, project_path, validation_result).
    validation_result is non-None when execution should be aborted early.
    """
    subtask_id = subtask.get("id", "")
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")[:60]

    initialize_subtask_logging(task_id, subtask_short_id, subtask_desc, project_id)

    project_path = get_project_path(project_id, task_id)
    validation_result = validate_subtask_environment(
        task_id, subtask, subtask_short_id, project_path, project_id
    )
    return subtask_id, subtask_short_id, project_path, validation_result


def _run_initial_agent(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    subtask: dict[str, Any],
    agent_slug: str,
    prompt: str,
    project_path: str,
    project_id: str,
) -> tuple[bool, list[Any], int, int, int, str, str | None]:
    """Execute the agent and run the self-healing loop.

    Returns (all_passed, step_results, self_fix_attempts,
             supervisor_guided_attempts, extensions_granted,
             initial_content, agent_session_id).
    """
    steps = subtask.get("steps_from_table") or subtask.get("steps") or []

    logger.info(
        "Executing in project",
        subtask_id=subtask_short_id,
        project_path=project_path,
        prompt_length=len(prompt),
        agent_slug=agent_slug,
    )

    response, agent_session_id = execute_agent_initial(
        task_id, subtask_short_id, prompt, agent_slug, project_path, project_id,
    )

    all_passed, step_results, self_fix_attempts, supervisor_guided_attempts, extensions_granted, _ = (
        run_self_healing_loop(
            task_id, subtask_id, subtask_short_id, subtask,
            steps, project_path, project_id,
            agent_slug, agent_session_id, response.content,
        )
    )

    return (
        all_passed, step_results,
        self_fix_attempts, supervisor_guided_attempts, extensions_granted,
        response.content, agent_session_id,
    )


def _apply_fallbacks(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    subtask: dict[str, Any],
    subtask_type: str | None,
    agent_slug: str,
    prompt: str,
    project_path: str,
    project_id: str,
    agent_override: str | None,
    all_passed: bool,
    step_results: list[Any],
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    extensions_granted: int,
) -> tuple[bool, list[Any], str, int, int, int]:
    """Apply fallback strategies after the primary self-healing loop.

    Returns (all_passed, step_results, agent_slug, self_fix_attempts,
             supervisor_guided_attempts, extensions_granted).
    """
    steps = subtask.get("steps_from_table") or subtask.get("steps") or []
    return execute_with_fallbacks(
        task_id, subtask_id, subtask_short_id, subtask, subtask_type,
        steps, project_path, project_id, agent_slug, prompt,
        all_passed, step_results, self_fix_attempts, supervisor_guided_attempts,
        extensions_granted, agent_override,
    )


def execute_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    issue_counts: dict[str, int],
    task_type: str | None = None,
    agent_override: str | None = None,
) -> dict[str, Any]:
    """Execute a single subtask with fresh context and self-healing retry loop."""
    start_time = time.time()

    try:
        subtask_id, subtask_short_id, project_path, validation_result = _setup_subtask(
            task_id, subtask, project_id
        )
        if validation_result:
            return validation_result

        subtask_type = subtask.get("subtask_type")
        agent_slug = agent_override or get_agent_for_subtask(subtask_type, task_type)
        prompt, prompt_snapshot = build_subtask_prompt_payload(task_id, subtask, project_id, project_path)
        emit_prompt_harness_snapshot(task_id, prompt_snapshot)

        all_passed, step_results, self_fix_attempts, supervisor_guided_attempts, extensions_granted, initial_content, _ = (
            _run_initial_agent(
                task_id, subtask_id, subtask_short_id, subtask,
                agent_slug, prompt, project_path, project_id,
            )
        )

        all_passed, step_results, agent_slug, self_fix_attempts, supervisor_guided_attempts, extensions_granted = (
            _apply_fallbacks(
                task_id, subtask_id, subtask_short_id, subtask, subtask_type,
                agent_slug, prompt, project_path, project_id,
                agent_override,
                all_passed, step_results, self_fix_attempts,
                supervisor_guided_attempts, extensions_granted,
            )
        )

        all_passed, step_results = _ensure_mergeable_work_product(
            task_id=task_id,
            subtask_short_id=subtask_short_id,
            project_path=project_path,
            project_id=project_id,
            all_passed=all_passed,
            step_results=step_results,
        )

        return process_final_result(
            task_id, subtask_id, subtask_short_id, project_id,
            all_passed, step_results, initial_content,
            time.time() - start_time,
            self_fix_attempts, supervisor_guided_attempts, extensions_granted,
            issue_counts, subtask_type=subtask_type,
        )

    except ExecutionInterrupted:
        raise
    except Exception as e:
        return handle_execution_error(task_id, subtask_short_id, project_id, e, issue_counts)


MAX_ITERATIONS = 50
