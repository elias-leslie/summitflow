"""Idea triage task using Agent Hub complete().

Triages incoming ideas to assess clarity and ask clarifying questions.
"""

from __future__ import annotations

import json
from typing import Any

from ...constants import AGENT_TRIAGER
from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.task_spirit import create_task_spirit

logger = get_logger(__name__)


def triage_idea(task_id: str, project_id: str) -> dict[str, Any]:
    """Triage a task using the triager agent.

    Uses Agent Hub complete() with the triager agent to assess:
    - Clarity of the task
    - Whether clarifying questions are needed
    - Suggested complexity
    - Dependency conflicts with active/queued tasks

    If clear (READY), moves task to Planning status.
    If unclear (NEEDS_CLARIFICATION), adds questions to events log.
    If rejected (REJECT), marks task as cancelled.

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

    # Gather context about existing active/queued tasks for conflict detection
    active_context = ""
    try:
        active_tasks: list[dict[str, Any]] = []
        for status in ("running", "queue", "pending"):
            active_tasks.extend(task_store.list_tasks(project_id=project_id, status_filter=status))
        if active_tasks:
            task_titles = [f"- {t.get('title', '')}" for t in active_tasks[:20]]
            active_context = (
                "\n\nExisting active/queued tasks in this project:\n"
                + "\n".join(task_titles)
                + "\n\nCheck for duplicates or conflicts."
            )
    except Exception:
        pass  # Non-critical context enrichment

    prompt = f"""Assess this task for clarity, feasibility, and readiness:

Title: {title}
Description: {description or "(no description provided)"}{active_context}

Provide your assessment in JSON format:
{{
    "status": "READY" | "NEEDS_CLARIFICATION" | "REJECT",
    "objective": "Single measurable goal",
    "spirit": "Core intent - what TO accomplish",
    "anti": "What should absolutely NOT be done",
    "requirements": ["List of acceptance criteria"],
    "suggested_complexity": "SIMPLE" | "STANDARD" | "COMPLEX",
    "priority": "critical" | "high" | "medium" | "low",
    "clarifying_questions": ["Only if NEEDS_CLARIFICATION"],
    "reject_reason": "Only if REJECT",
    "reasoning": "Brief explanation"
}}"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug=AGENT_TRIAGER.replace("agent:", ""),
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
    """Parse the triager agent's response.

    Expected format:
    {
        "status": "READY" | "NEEDS_CLARIFICATION" | "REJECT",
        "objective": "...",
        "requirements": [...],
        "suggested_complexity": "SIMPLE" | "STANDARD" | "COMPLEX",
        "priority": "critical" | "high" | "medium" | "low",
        "clarifying_questions": [...],
        "reject_reason": "...",
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
        "clarifying_questions": [
            "Could you provide more details about what you want to accomplish?"
        ],
        "reasoning": "Could not parse agent response, requesting clarification",
    }


def _process_triage_result(task_id: str, result: dict[str, Any]) -> None:
    """Process triage result and update task accordingly.

    If READY: Create task_spirit with objective and move to 'queue' status for planning.
    If NEEDS_CLARIFICATION: Add questions to events log and block.
    If REJECT: Cancel the task.
    """
    status = result.get("status", "").upper()

    # Handle REJECT verdict
    if status == "REJECT":
        reason = result.get("reject_reason", result.get("reasoning", "Rejected by triager"))
        task_store.update_task_status(task_id, "cancelled")
        log_task_event(task_id, f"Triage: REJECTED - {reason}")
        logger.info("Triage rejected task", task_id=task_id, reason=reason[:100])
        return

    if status in ("CLEAR", "READY"):
        complexity = result.get("suggested_complexity", "STANDARD")
        objective = result.get("objective", "")
        requirements = result.get("requirements", [])
        spirit = result.get("spirit", "")
        anti = result.get("anti", "")

        spirit_anti = None
        if spirit or anti:
            spirit_anti = f"SPIRIT: {spirit}. ANTI: {anti}."

        task_store.update_task(task_id, complexity=complexity)

        if objective:
            create_task_spirit(
                task_id=task_id,
                objective=objective,
                spirit_anti=spirit_anti,
                complexity=complexity,
                done_when=requirements if requirements else None,
            )
            logger.info("Created task spirit", task_id=task_id, objective=objective[:50])

        task_store.update_task_status(task_id, "queue")
        log_task_event(
            task_id,
            f"Triage complete: CLEAR - Complexity: {complexity}. Moving to queue.",
        )
        logger.info("Triage clear, moving to queue", task_id=task_id, complexity=complexity)

    else:
        questions = result.get("clarifying_questions", [])
        if questions:
            questions_text = "\n".join(f"- {q}" for q in questions)
            log_task_event(
                task_id,
                f"Triage: Needs clarification\n{questions_text}",
            )
        task_store.update_task_status(task_id, "blocked")
        logger.info("Triage needs clarification", task_id=task_id, questions=len(questions))
