"""Autonomous planning task using Agent Hub run_agent().

Creates implementation plans by running the planner agent in the project directory.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.context_gatherer import (
    collect_precision_code_search_context,
)
from ...storage import log_task_event
from ...storage import tasks as task_store
from .planning_prompt import build_planning_prompt as _build_planning_prompt
from .planning_prompt import planning_feedback_payload as _planning_feedback_payload
from .planning_routing import route_based_on_complexity, supervisor_validate_plan
from .planning_storage import save_plan_to_database

logger = get_logger(__name__)


def _fetch_task_for_planning(task_id: str) -> dict[str, Any] | None:
    """Fetch the task and log a warning if not found.

    Args:
        task_id: The task ID to fetch

    Returns:
        Task dict, or None if not found
    """
    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for planning", task_id=task_id)
    return task


def _process_plan_result(
    task_id: str, project_id: str, title: str, description: str, plan_data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the parsed plan, persist it, and route by complexity.

    Args:
        task_id: The task ID
        project_id: The project ID (unused here but kept for future use)
        title: Task title
        description: Task description
        plan_data: Parsed plan dict from the planner agent

    Returns:
        Result dict with status and subtasks_created count
    """
    subtask_count = len(plan_data.get("subtasks", []))
    if subtask_count == 0:
        logger.warning("Planner produced 0 subtasks", task_id=task_id)
        log_task_event(task_id, "Planning failed: planner produced no subtasks")
        return {
            "task_id": task_id,
            "status": "error",
            "message": "Planner produced no subtasks",
        }

    save_plan_to_database(task_id, plan_data)
    route_based_on_complexity(task_id, title, description)

    return {
        "task_id": task_id,
        "status": "completed",
        "subtasks_created": subtask_count,
    }


def create_plan(task_id: str, project_id: str) -> dict[str, Any]:
    """Create an implementation plan using the planner agent.

    Uses Agent Hub run_agent() with the planner agent to:
    1. Analyze the task requirements
    2. Create subtasks with steps
    3. Route based on complexity

    Args:
        task_id: The task ID to plan
        project_id: The project ID

    Returns:
        Planning result with subtasks created
    """
    logger.info("Starting autonomous planning", task_id=task_id, project_id=project_id)

    task = _fetch_task_for_planning(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    title = task.get("title", "")
    description = task.get("description", "")
    precision_context = collect_precision_code_search_context(
        project_id,
        [title, description],
        budget_tokens=1200,
    ).prompt_context
    planning_feedback = _planning_feedback_payload(task_id)
    prompt = _build_planning_prompt(title, description, precision_context, planning_feedback)

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="planner",
            external_id=task_id,
        )

        plan_data = _parse_plan_response(response.content)
        return _process_plan_result(task_id, project_id, title, description, plan_data)

    except Exception as e:
        logger.warning("Planning failed", task_id=task_id, error=str(e))
        log_task_event(task_id, f"Planning failed: {e}")
        return {"task_id": task_id, "status": "error", "message": str(e)}


def _parse_plan_response(content: str) -> dict[str, Any]:
    """Parse the planner agent's response into structured plan data.

    Args:
        content: Raw agent response content

    Returns:
        Parsed plan data with objective, subtasks, and constraints
    """
    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            return parsed
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse plan JSON", error=str(e))

    return {"objective": "Could not parse plan", "subtasks": [], "constraints": []}


# Re-export internal functions for backward compatibility with tests
_supervisor_validate_plan = supervisor_validate_plan
_save_plan_to_database = save_plan_to_database
_route_based_on_complexity = route_based_on_complexity
