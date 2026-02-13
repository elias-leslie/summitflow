"""Autonomous planning task using Agent Hub run_agent().

Creates implementation plans by running the planner agent in the project directory.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.complexity_assessor import ComplexityAssessor, ComplexityTier
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.subtasks import bulk_add_subtask_dependencies, bulk_create_subtasks
from ...storage.task_spirit import create_task_spirit, get_task_spirit

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

    prompt = f"""Title: {title}
Description: {description or "(no description)"}"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="planner",
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
        log_task_event(task_id, f"Planning failed: {e}")
        return {"task_id": task_id, "status": "error", "message": str(e)}


def _parse_plan_response(content: str) -> dict[str, Any]:
    """Parse the planner agent's response into structured plan data."""
    import re

    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            _validate_and_fix_plan(parsed)
            return parsed
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse plan JSON", error=str(e))

    return {"objective": "Could not parse plan", "subtasks": [], "constraints": []}


_ABSOLUTE_CD_PATTERN = re.compile(r"\bcd\s+/[^\s;|&]+")
_ABSOLUTE_PATH_PREFIX = re.compile(r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+")
_SMALL_CONTEXT_WINDOW = re.compile(r"-A[1-5]\b")
_CHAINED_RG_PIPE = re.compile(r"rg\s.+\|\s*rg")
_HEAD_TAIL_USAGE = re.compile(r"\bhead\b|\btail\b")


def _validate_verify_command(cmd: str) -> str | None:
    """Return error message if verify_command has absolute paths, else None."""
    if _ABSOLUTE_CD_PATTERN.search(cmd):
        return f"verify_command contains absolute cd path: {cmd[:80]}"
    if _ABSOLUTE_PATH_PREFIX.search(cmd):
        return f"verify_command contains absolute path: {cmd[:80]}"
    return None


def _validate_and_fix_plan(plan: dict[str, Any]) -> None:
    """Validate and fix common issues in verify_commands."""
    for subtask in plan.get("subtasks", []):
        for step in subtask.get("steps", []):
            verify = step.get("verify_command", "")

            if verify:
                error = _validate_verify_command(verify)
                if error:
                    logger.warning(
                        "invalid_verify_command",
                        subtask=subtask.get("subtask_id"),
                        error=error,
                    )
                    step["verify_command"] = None

                elif "cat " in verify and "| grep" in verify:
                    step["verify_command"] = re.sub(
                        r"cat\s+(\S+)\s*\|\s*grep\s+(.+)",
                        r"rg \2 \1",
                        verify,
                    )

                elif verify.startswith("grep "):
                    step["verify_command"] = "rg " + verify[5:]

                if _SMALL_CONTEXT_WINDOW.search(verify):
                    logger.warning(
                        "small_context_window",
                        subtask=subtask.get("subtask_id"),
                        verify_command=verify[:80],
                    )

                if _CHAINED_RG_PIPE.search(verify):
                    logger.warning(
                        "chained_rg_pipe",
                        subtask=subtask.get("subtask_id"),
                        verify_command=verify[:80],
                    )

                if _HEAD_TAIL_USAGE.search(verify):
                    logger.warning(
                        "head_tail_usage",
                        subtask=subtask.get("subtask_id"),
                        verify_command=verify[:80],
                    )



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
                    formatted_steps.append(
                        {
                            "description": step.get("description", ""),
                            "verify_command": step.get("verify_command"),
                        }
                    )
                else:
                    formatted_steps.append({"description": str(step)})

            formatted_subtasks.append(
                {
                    "subtask_id": st.get("subtask_id", f"{len(formatted_subtasks) + 1}.1"),
                    "phase": st.get("phase"),
                    "subtask_type": st.get("subtask_type"),
                    "description": st.get("description", ""),
                    "steps": formatted_steps,
                }
            )

        bulk_create_subtasks(task_id, formatted_subtasks)
        logger.info("Created subtasks from plan", task_id=task_id, count=len(formatted_subtasks))

        # Store subtask dependencies from planner output
        deps: list[tuple[str, str]] = []
        for st in subtasks_data:
            sid = st.get("subtask_id", "")
            for dep in st.get("depends_on", []):
                if dep and sid:
                    deps.append((sid, dep))
        if deps:
            try:
                bulk_add_subtask_dependencies(task_id, deps)
                logger.info("Created subtask dependencies", task_id=task_id, count=len(deps))
            except Exception as e:
                logger.warning("Failed to create dependencies", task_id=task_id, error=str(e))


def _supervisor_validate_plan(task_id: str, reasoning: str, project_id: str) -> bool:
    """Ask supervisor to validate a COMPLEX plan. Returns True to proceed."""
    prompt = (
        f"Task {task_id} was classified as COMPLEX.\n"
        f"Assessor reasoning: {reasoning}\n\n"
        f"Should this task proceed to execution? "
        f"Reply APPROVED to proceed or BLOCKED with your concern."
    )
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id,
        )
        return "BLOCKED" not in response.content.upper()
    except Exception:
        return True


def _route_based_on_complexity(task_id: str, title: str, description: str) -> None:
    """Route task based on complexity assessment.

    SIMPLE/STANDARD -> Queue for execution
    COMPLEX -> Supervisor validates, then queue or blocked
    """
    assessor = ComplexityAssessor()
    result = assessor.assess_sync(title, description)

    task_store.update_task(task_id, complexity=result.tier.value)

    task = task_store.get_task(task_id)
    project_id = task.get("project_id", "summitflow") if task else "summitflow"

    if result.tier == ComplexityTier.COMPLEX:
        approved = _supervisor_validate_plan(task_id, result.reasoning, project_id)
        if approved:
            task_store.update_task_status(task_id, "queue")
            log_task_event(
                task_id,
                f"Complexity: {result.tier.value} - Supervisor approved, queued for execution. "
                f"Reason: {result.reasoning}",
            )
            logger.info(
                "Complex task supervisor-approved, queued",
                task_id=task_id,
                complexity=result.tier.value,
            )
        else:
            task_store.update_task_status(task_id, "blocked")
            log_task_event(
                task_id,
                f"Complexity: {result.tier.value} - Supervisor blocked task. "
                f"Reason: {result.reasoning}",
            )
            logger.info(
                "Complex task blocked by supervisor",
                task_id=task_id,
                complexity=result.tier.value,
            )
    else:
        task_store.update_task_status(task_id, "queue")
        log_task_event(
            task_id,
            f"Complexity: {result.tier.value} - Plan ready, queued for execution.",
        )
        logger.info(
            "Task queued for execution",
            task_id=task_id,
            complexity=result.tier.value,
        )
