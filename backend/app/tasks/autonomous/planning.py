"""Autonomous planning task using Agent Hub run_agent().

Creates implementation plans by running the planner agent in the task's worktree.
"""

from __future__ import annotations

import json
from typing import Any

from celery import Task as CeleryTask
from celery import shared_task

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.complexity_assessor import ComplexityAssessor, ComplexityTier
from ...storage import tasks as task_store
from ...storage.subtasks import bulk_create_subtasks
from ...storage.task_spirit import create_task_spirit, get_task_spirit

logger = get_logger(__name__)


@shared_task(bind=True, name="autonomous.create_plan")  # type: ignore[untyped-decorator]
def create_plan(self: CeleryTask, task_id: str, project_id: str) -> dict[str, Any]:
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

    prompt = f"""Create an implementation plan for this task:

Title: {title}
Description: {description or "(no description)"}

Provide a structured plan with:
1. Objective (one sentence)
2. Subtasks with steps (each step must have verify_command and expected_output)
3. Any constraints or considerations

Output as JSON with this structure:
{{
    "objective": "...",
    "subtasks": [
        {{
            "subtask_id": "1.1",
            "phase": "backend|frontend|research|testing",
            "description": "...",
            "steps": [
                {{
                    "description": "...",
                    "verify_command": "command to verify",
                    "expected_output": "expected output"
                }}
            ]
        }}
    ],
    "constraints": ["..."]
}}"""

    try:
        client = get_sync_client()
        response = client.run_agent(
            agent_slug="planner",
            prompt=prompt,
            working_dir=f"/home/kasadis/{project_id}",
        )

        plan_data = _parse_plan_response(response.content)
        _save_plan_to_database(task_id, plan_data)
        _route_based_on_complexity(task_id, title, description)

        return {
            "task_id": task_id,
            "status": "completed",
            "subtasks_created": len(plan_data.get("subtasks", [])),
        }

    except Exception as e:
        logger.warning("Planning failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "blocked")
        task_store.append_progress_log(task_id, f"Planning failed: {e}")
        return {"task_id": task_id, "status": "error", "message": str(e)}


def _parse_plan_response(content: str) -> dict[str, Any]:
    """Parse the planner agent's response into structured plan data."""
    import re

    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            return parsed
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse plan JSON", error=str(e))

    return {"objective": "Could not parse plan", "subtasks": [], "constraints": []}


def _save_plan_to_database(task_id: str, plan_data: dict[str, Any]) -> None:
    """Save parsed plan to database using existing storage functions."""
    objective = plan_data.get("objective", "")
    subtasks_data = plan_data.get("subtasks", [])
    constraints = plan_data.get("constraints", [])

    spirit = get_task_spirit(task_id)
    if not spirit:
        create_task_spirit(task_id=task_id, objective=objective, constraints=constraints)
    else:
        from ...storage.task_spirit import update_task_spirit

        update_task_spirit(task_id, objective=objective, constraints=constraints)

    if subtasks_data:
        formatted_subtasks: list[dict[str, Any]] = []
        for st in subtasks_data:
            steps = st.get("steps", [])
            formatted_steps = []
            for step in steps:
                if isinstance(step, dict):
                    formatted_steps.append({
                        "description": step.get("description", ""),
                        "verify_command": step.get("verify_command"),
                        "expected_output": step.get("expected_output"),
                    })
                else:
                    formatted_steps.append({"description": str(step)})

            formatted_subtasks.append({
                "subtask_id": st.get("subtask_id", f"{len(formatted_subtasks) + 1}.1"),
                "phase": st.get("phase"),
                "description": st.get("description", ""),
                "steps": formatted_steps,
            })

        bulk_create_subtasks(task_id, formatted_subtasks)
        logger.info("Created subtasks from plan", task_id=task_id, count=len(formatted_subtasks))


def _route_based_on_complexity(task_id: str, title: str, description: str) -> None:
    """Route task based on complexity assessment.

    SIMPLE/STANDARD -> Queue for execution
    COMPLEX -> Human Review for discussion
    """
    assessor = ComplexityAssessor()
    result = assessor.assess_sync(title, description)

    task_store.update_task(task_id, complexity=result.tier.value)

    if result.tier == ComplexityTier.COMPLEX:
        task_store.update_task_status(task_id, "human_review")
        task_store.append_progress_log(
            task_id,
            f"Complexity: {result.tier.value} - Routing to Human Review for discussion. "
            f"Reason: {result.reasoning}",
        )
        logger.info(
            "Complex task routed to human review",
            task_id=task_id,
            complexity=result.tier.value,
        )
    else:
        task_store.update_task_status(task_id, "queue")
        task_store.append_progress_log(
            task_id,
            f"Complexity: {result.tier.value} - Plan ready, queued for execution.",
        )
        logger.info(
            "Task queued for execution",
            task_id=task_id,
            complexity=result.tier.value,
        )
