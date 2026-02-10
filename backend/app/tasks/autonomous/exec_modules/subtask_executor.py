"""Subtask execution with self-healing retry loop."""

from __future__ import annotations

import time
import traceback
from typing import Any

from ....core.debug import debug, debug_error, debug_section
from ....logging_config import get_logger
from .agent_execution import execute_agent_initial
from .agent_routing import get_agent_for_subtask, get_fallback_agents
from .events import emit_error, emit_log, emit_progress
from .prompts import build_subtask_prompt
from .result_processing import process_final_result
from .retry_loop import run_self_healing_loop
from .steps import compute_issue_id
from .worktree import check_worktree_health, get_project_path

logger = get_logger(__name__)


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
    subtask_id = subtask.get("id", "")
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")[:60]

    debug_section(f"Subtask {subtask_short_id}", task_id=task_id, project_id=project_id)
    debug(
        "Starting subtask execution",
        task_id=task_id,
        project_id=project_id,
        subtask_id=subtask_short_id,
        description=subtask_desc,
    )
    logger.info("Executing subtask", task_id=task_id, subtask_id=subtask_short_id)
    emit_log(
        task_id,
        "info",
        f"Starting subtask {subtask_short_id}: {subtask_desc}",
        project_id=project_id,
    )
    emit_progress(
        task_id, subtask_id=subtask_short_id, status="in_progress", project_id=project_id
    )

    try:
        # Use task worktree if available for isolated execution
        project_path = get_project_path(project_id, task_id)

        if not check_worktree_health(project_path, task_id, project_id):
            return {
                "subtask_id": subtask_short_id,
                "status": "failed",
                "reason": "worktree_invalid",
            }

        prompt = build_subtask_prompt(task_id, subtask, project_id, project_path)

        # Resolve which agent to use: override > subtask_type > task_type > default
        subtask_type = subtask.get("subtask_type")
        agent_slug = agent_override or get_agent_for_subtask(subtask_type, task_type)

        logger.info(
            "Executing in project",
            subtask_id=subtask_short_id,
            project_path=project_path,
            prompt_length=len(prompt),
            agent_slug=agent_slug,
        )

        # Execute initial agent call
        response, agent_session_id = execute_agent_initial(
            task_id, subtask_short_id, prompt, agent_slug, project_path, project_id
        )

        # Validate steps before starting retry loop
        steps = subtask.get("steps_from_table", [])
        if not steps:
            emit_log(
                task_id,
                "error",
                f"Subtask {subtask_short_id} has 0 steps — cannot verify",
                source="orchestrator",
                project_id=project_id,
            )
            return {
                "subtask_id": subtask_short_id,
                "status": "failed",
                "passed": False,
                "reason": "zero_steps",
                "step_results": [],
            }

        # Run self-healing retry loop
        (
            all_passed,
            step_results,
            self_fix_attempts,
            supervisor_guided_attempts,
            extensions_granted,
            _,
        ) = run_self_healing_loop(
            task_id,
            subtask_id,
            subtask_short_id,
            subtask,
            steps,
            project_path,
            project_id,
            agent_slug,
            agent_session_id,
            response.content,
        )

        # Cross-agent fallback: if primary agent failed, try alternative agents
        if not all_passed and not agent_override:
            fallback_agents = get_fallback_agents(subtask_type, agent_slug)
            for fallback_slug in fallback_agents:
                emit_log(
                    task_id,
                    "info",
                    f"Cross-agent fallback: trying {fallback_slug} for subtask {subtask_short_id}",
                    project_id=project_id,
                )
                try:
                    fallback_prompt = (
                        f"Previous agent ({agent_slug}) failed this subtask after "
                        f"{self_fix_attempts + supervisor_guided_attempts} attempts.\n\n"
                        f"{prompt}\n\nTry a different approach."
                    )
                    fb_response, fb_session = execute_agent_initial(
                        task_id, subtask_short_id, fallback_prompt,
                        fallback_slug, project_path, project_id,
                    )
                    (
                        all_passed, step_results, fb_self, fb_super, fb_ext, _,
                    ) = run_self_healing_loop(
                        task_id, subtask_id, subtask_short_id, subtask,
                        steps, project_path, project_id,
                        fallback_slug, fb_session, fb_response.content,
                    )
                    if all_passed:
                        emit_log(
                            task_id, "info",
                            f"Cross-agent fallback to {fallback_slug} succeeded",
                            project_id=project_id,
                        )
                        agent_slug = fallback_slug
                        self_fix_attempts += fb_self
                        supervisor_guided_attempts += fb_super
                        extensions_granted += fb_ext
                        break
                except Exception as fb_err:
                    logger.warning(
                        "Cross-agent fallback failed",
                        fallback=fallback_slug, error=str(fb_err),
                    )

        # Process final result
        duration = time.time() - start_time
        return process_final_result(
            task_id,
            subtask_id,
            subtask_short_id,
            project_id,
            all_passed,
            step_results,
            response.content,
            duration,
            self_fix_attempts,
            supervisor_guided_attempts,
            extensions_granted,
            issue_counts,
            subtask_type=subtask_type,
        )

    except Exception as e:
        logger.warning(
            "Subtask execution failed",
            subtask_id=subtask_short_id,
            error=str(e),
            traceback=traceback.format_exc(),
        )
        error_str = str(e)
        issue_id = compute_issue_id(error_str)
        issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
        emit_error(
            task_id, f"Subtask {subtask_short_id} error: {error_str}", project_id=project_id
        )
        debug_error(
            f"Subtask {subtask_short_id} exception",
            task_id=task_id,
            project_id=project_id,
            error=error_str,
            issue_id=issue_id,
        )
        return {
            "subtask_id": subtask_short_id,
            "status": "failed",
            "error": error_str,
            "issue_id": issue_id,
            "issue_count": issue_counts[issue_id],
        }

# Re-export constant used by orchestrator.py
MAX_ITERATIONS = 50
