"""Single task execution unit."""

from __future__ import annotations

import time
from typing import Any

from ....logging_config import get_logger
from .agent_execution import execute_agent_initial
from .agent_helpers import agent_completion_failure
from .agent_routing import get_agent_for_subtask
from .ah_events import emit_prompt_harness_snapshot
from .checkout import get_project_path
from .git_work_product import ensure_committed_work_product
from .interruption import ExecutionInterrupted
from .prompts import build_subtask_prompt_payload
from .quality_check import run_execution_quality_check
from .result_processing import process_final_result
from .subtask_helpers import handle_execution_error, initialize_subtask_logging
from .subtask_validation import validate_subtask_environment

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
) -> tuple[bool, list[Any], str]:
    """Execute the agent once, then run task-scoped verification."""
    steps = subtask.get("steps_from_table") or subtask.get("steps") or []

    logger.info(
        "Executing in project",
        subtask_id=subtask_short_id,
        project_path=project_path,
        prompt_length=len(prompt),
        agent_slug=agent_slug,
    )

    response, _agent_session_id = execute_agent_initial(
        task_id, subtask_short_id, prompt, agent_slug, project_path, project_id,
    )
    failure = agent_completion_failure(response)
    if failure:
        step_result = {
            "step_number": 0,
            "passed": False,
            "output": failure,
            "reason": "agent_interrupted",
            "returncode": 1,
        }
        return False, [step_result], response.content

    all_passed, step_results = (
        run_execution_quality_check(task_id, subtask_id, steps, project_path, project_id)
    )

    return all_passed, step_results, response.content


def execute_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    issue_counts: dict[str, int],
    task_type: str | None = None,
    agent_override: str | None = None,
) -> dict[str, Any]:
    """Execute the task once with fresh context."""
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

        all_passed, step_results, initial_content = (
            _run_initial_agent(
                task_id, subtask_id, subtask_short_id, subtask,
                agent_slug, prompt, project_path, project_id,
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
            0, 0, 0,
            issue_counts, subtask_type=subtask_type,
        )

    except ExecutionInterrupted:
        raise
    except Exception as e:
        return handle_execution_error(task_id, subtask_short_id, project_id, e, issue_counts)


MAX_ITERATIONS = 50
