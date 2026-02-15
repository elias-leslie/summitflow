"""Subtask execution with self-healing retry loop."""

from __future__ import annotations

import time
from typing import Any

from ....logging_config import get_logger
from .agent_execution import execute_agent_initial
from .agent_routing import get_agent_for_subtask
from .prompts import build_subtask_prompt
from .result_processing import process_final_result
from .retry_loop import run_self_healing_loop
from .subtask_fallback import execute_with_fallbacks
from .subtask_helpers import handle_execution_error, initialize_subtask_logging
from .subtask_validation import validate_subtask_environment
from .worktree import get_project_path

logger = get_logger(__name__)


def execute_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    issue_counts: dict[str, int],
    task_type: str | None = None,
    agent_override: str | None = None,
    tier_preference: str | None = None,
) -> dict[str, Any]:
    """Execute a single subtask with fresh context and self-healing retry loop."""
    start_time = time.time()
    subtask_id = subtask.get("id", "")
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")[:60]

    initialize_subtask_logging(task_id, subtask_short_id, subtask_desc, project_id)

    try:
        project_path = get_project_path(project_id, task_id)
        validation_result = validate_subtask_environment(
            task_id, subtask, subtask_short_id, project_path, project_id
        )
        if validation_result:
            return validation_result

        steps = subtask.get("steps_from_table", [])
        prompt = build_subtask_prompt(task_id, subtask, project_id, project_path)
        subtask_type = subtask.get("subtask_type")
        agent_slug = agent_override or get_agent_for_subtask(subtask_type, task_type)

        logger.info(
            "Executing in project",
            subtask_id=subtask_short_id,
            project_path=project_path,
            prompt_length=len(prompt),
            agent_slug=agent_slug,
        )

        response, agent_session_id = execute_agent_initial(
            task_id, subtask_short_id, prompt, agent_slug, project_path, project_id,
            tier_preference=tier_preference,
        )

        all_passed, step_results, self_fix_attempts, supervisor_guided_attempts, extensions_granted, _ = (
            run_self_healing_loop(
                task_id, subtask_id, subtask_short_id, subtask,
                steps, project_path, project_id,
                agent_slug, agent_session_id, response.content,
                tier_preference=tier_preference,
            )
        )

        all_passed, step_results, agent_slug, self_fix_attempts, supervisor_guided_attempts, extensions_granted = (
            execute_with_fallbacks(
                task_id, subtask_id, subtask_short_id, subtask, subtask_type,
                steps, project_path, project_id, agent_slug, prompt,
                all_passed, step_results, self_fix_attempts, supervisor_guided_attempts,
                extensions_granted, agent_override, tier_preference,
            )
        )

        return process_final_result(
            task_id, subtask_id, subtask_short_id, project_id,
            all_passed, step_results, response.content,
            time.time() - start_time,
            self_fix_attempts, supervisor_guided_attempts, extensions_granted,
            issue_counts, subtask_type=subtask_type,
        )

    except Exception as e:
        return handle_execution_error(task_id, subtask_short_id, project_id, e, issue_counts)


MAX_ITERATIONS = 50
