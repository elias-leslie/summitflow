"""Autonomous planning task using Agent Hub run_agent().

Creates implementation plans by running the planner agent in the project directory.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import log_task_event
from ...storage import tasks as task_store
from .planning_routing import route_based_on_complexity, supervisor_validate_plan
from .planning_storage import save_plan_to_database
from .planning_validation import validate_and_fix_plan

logger = get_logger(__name__)


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

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for planning", task_id=task_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    title = task.get("title", "")
    description = task.get("description", "")

    prompt = f"""Create an implementation plan for this task.

Title: {title}
Description: {description or "(no description)"}

You MUST respond with a JSON object (no markdown, no explanation outside the JSON):
{{
    "objective": "Clear 1-2 sentence objective",
    "subtasks": [
        {{
            "subtask_id": "1.1",
            "phase": "implementation",
            "subtask_type": "backend|frontend|ui-design|refactor|bug-fix|test|config",
            "description": "What this subtask accomplishes",
            "steps": [
                {{
                    "description": "Specific implementation step",
                    "verify_command": "rg -q 'pattern' file && echo OK"
                }}
            ],
            "depends_on": []
        }}
    ],
    "constraints": ["Any constraints or non-goals"]
}}

Rules for verify_command:
- Use relative paths (commands run in worktree, not main repo)
- Must exit non-zero on failure: rg -q, test -f, pytest
- No trivial commands (echo, true, exit 0)
- No absolute paths (/home/..., /tmp/...)"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="planner",
        )

        plan_data = _parse_plan_response(response.content)

        subtask_count = len(plan_data.get("subtasks", []))
        if subtask_count == 0:
            logger.warning("Planner produced 0 subtasks", task_id=task_id)
            task_store.update_task_status(task_id, "blocked")
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

    except Exception as e:
        logger.warning("Planning failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "blocked")
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
            validate_and_fix_plan(parsed)
            return parsed
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse plan JSON", error=str(e))

    return {"objective": "Could not parse plan", "subtasks": [], "constraints": []}


# Re-export internal functions for backward compatibility with tests
_validate_and_fix_plan = validate_and_fix_plan
_supervisor_validate_plan = supervisor_validate_plan
_save_plan_to_database = save_plan_to_database
_route_based_on_complexity = route_based_on_complexity
