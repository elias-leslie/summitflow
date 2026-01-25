"""Idea triage task using Agent Hub complete().

Triages incoming ideas to assess clarity and ask clarifying questions.
"""

from __future__ import annotations

import json
from typing import Any

from celery import Task as CeleryTask
from celery import shared_task

from ...constants import AGENT_IDEA_INTAKE
from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import tasks as task_store

logger = get_logger(__name__)


@shared_task(bind=True, name="autonomous.triage_idea")  # type: ignore[untyped-decorator]
def triage_idea(self: CeleryTask, task_id: str, project_id: str) -> dict[str, Any]:
    """Triage an idea task using the idea-intake agent.

    Uses Agent Hub complete() with the idea-intake agent to assess:
    - Clarity of the idea
    - Whether clarifying questions are needed
    - Suggested complexity

    If clear, moves task to Planning status.
    If unclear, adds clarifying questions to task chat.

    Args:
        task_id: The task ID to triage
        project_id: The project ID

    Returns:
        Triage result with status and any questions
    """
    logger.info("Starting idea triage", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for triage", task_id=task_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    title = task.get("title", "")
    description = task.get("description", "")

    prompt = f"""Assess this idea for clarity and completeness:

Title: {title}
Description: {description or "(no description provided)"}

Provide your assessment in JSON format."""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug=AGENT_IDEA_INTAKE.replace("agent:", ""),
        )

        triage_result = _parse_triage_response(response.content)
        _process_triage_result(task_id, triage_result)

        return {
            "task_id": task_id,
            "status": "completed",
            "result": triage_result,
        }

    except Exception as e:
        logger.warning("Triage failed", task_id=task_id, error=str(e))
        return {
            "task_id": task_id,
            "status": "error",
            "message": str(e),
        }


def _parse_triage_response(content: str) -> dict[str, Any]:
    """Parse the idea-intake agent's response.

    Expected format:
    {
        "status": "CLEAR" | "NEEDS_CLARIFICATION",
        "objective": "...",
        "requirements": [...],
        "suggested_complexity": "SIMPLE" | "STANDARD" | "COMPLEX",
        "clarifying_questions": [...],
        "reasoning": "..."
    }
    """
    import re

    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            return parsed
    except json.JSONDecodeError:
        pass

    return {
        "status": "NEEDS_CLARIFICATION",
        "clarifying_questions": ["Could you provide more details about what you want to accomplish?"],
        "reasoning": "Could not parse agent response, requesting clarification",
    }


def _process_triage_result(task_id: str, result: dict[str, Any]) -> None:
    """Process triage result and update task accordingly.

    If CLEAR: Move task to 'queue' status for planning.
    If NEEDS_CLARIFICATION: Add questions to task chat/progress_log.
    """
    status = result.get("status", "").upper()

    if status == "CLEAR":
        complexity = result.get("suggested_complexity", "STANDARD")
        task_store.update_task(task_id, complexity=complexity)
        task_store.update_task_status(task_id, "queue")
        task_store.append_progress_log(
            task_id,
            f"Triage complete: CLEAR - Complexity: {complexity}. Moving to queue.",
        )
        logger.info("Triage clear, moving to queue", task_id=task_id, complexity=complexity)

    else:
        questions = result.get("clarifying_questions", [])
        if questions:
            questions_text = "\n".join(f"- {q}" for q in questions)
            task_store.append_progress_log(
                task_id,
                f"Triage: Needs clarification\n{questions_text}",
            )
        task_store.update_task_status(task_id, "blocked")
        logger.info("Triage needs clarification", task_id=task_id, questions=len(questions))
