"""Idea triage task using Agent Hub complete()."""

from __future__ import annotations

import json
import re
from typing import Any

from ...constants import AGENT_TRIAGER
from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.task_second_opinion import ensure_second_opinion_tracking
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.task_spirit import get_task_spirit, upsert_task_spirit
from ...storage.tasks.dedup import duplicate_task_exists

logger = get_logger(__name__)

_TRIAGE_PROMPT_TEMPLATE = (
    "Assess this task for clarity, feasibility, and readiness:\n\n"
    "Title: {title}\nDescription: {description}\n\n"
    'Provide your assessment in JSON format:\n{{\n'
    '    "status": "READY" | "NEEDS_CLARIFICATION" | "REJECT",\n'
    '    "objective": "Single measurable goal",\n'
    '    "spirit": "Core intent - what TO accomplish",\n'
    '    "anti": "What should absolutely NOT be done",\n'
    '    "done_when": ["List of completion conditions"],\n'
    '    "suggested_complexity": "SIMPLE" | "STANDARD" | "COMPLEX",\n'
    '    "priority": "critical" | "high" | "medium" | "low",\n'
    '    "clarifying_questions": ["Only if NEEDS_CLARIFICATION"],\n'
    '    "reject_reason": "Only if REJECT",\n'
    '    "reasoning": "Brief explanation"\n}}'
)


def _parse_triage_response(content: str) -> dict[str, Any]:
    """Parse the triager agent's response into a structured dict."""
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


def _handle_reject(task_id: str, result: dict[str, Any]) -> None:
    reason = result.get("reject_reason", result.get("reasoning", "Rejected by triager"))
    task_store.update_task_status(task_id, "cancelled")
    log_task_event(task_id, f"Triage: REJECTED - {reason}")
    logger.info("Triage rejected task", task_id=task_id, reason=reason[:100])


def _handle_ready(task_id: str, result: dict[str, Any]) -> None:
    complexity = result.get("suggested_complexity", "STANDARD")
    objective = result.get("objective", "")
    done_when = result.get("done_when") or result.get("requirements", [])

    updates: dict[str, Any] = {"complexity": complexity}
    if objective:
        updates["description"] = objective
    task_store.update_task(task_id, **updates)
    if objective:
        upsert_task_spirit(
            task_id=task_id,
            complexity=complexity,
            done_when=done_when if done_when else None,
        )
        logger.info("Created task spirit", task_id=task_id, objective=objective[:50])

    task = task_store.get_task(task_id)
    if task:
        ensure_second_opinion_tracking(task_id, task, source="triage")

    task_store.update_task_status(task_id, "pending")
    log_task_event(task_id, f"Triage complete: CLEAR - Complexity: {complexity}. Moving to pending.")
    logger.info("Triage clear, moving to pending", task_id=task_id, complexity=complexity)


def _handle_needs_clarification(task_id: str, result: dict[str, Any]) -> None:
    questions = result.get("clarifying_questions", [])
    if questions:
        questions_text = "\n".join(f"- {q}" for q in questions)
        log_task_event(task_id, f"Triage: Needs clarification\n{questions_text}")
    task_store.update_task_status(task_id, "failed")
    logger.info("Triage needs clarification", task_id=task_id, questions=len(questions))


def _process_triage_result(task_id: str, result: dict[str, Any]) -> None:
    """Process triage result and update task accordingly."""
    status = result.get("status", "").upper()
    if status == "REJECT":
        _handle_reject(task_id, result)
    elif status in ("CLEAR", "READY"):
        _handle_ready(task_id, result)
    else:
        _handle_needs_clarification(task_id, result)


def _check_duplicate(task_id: str, project_id: str, title: str, description: str) -> dict[str, Any] | None:
    """Return a completed-duplicate result dict if a duplicate exists, else None."""
    dup_id = duplicate_task_exists(project_id, title, exclude_task_id=task_id, description=description)
    if not dup_id:
        return None
    task_store.update_task_status(task_id, "cancelled")
    log_task_event(task_id, f"Triage: REJECTED - Duplicate of {dup_id} (deterministic match)")
    logger.info("Triage rejected duplicate", task_id=task_id, duplicate_of=dup_id)
    return {"task_id": task_id, "status": "completed", "result": {"status": "REJECT", "reject_reason": f"Duplicate of {dup_id}"}}


def triage_idea(task_id: str, project_id: str) -> dict[str, Any]:
    """Triage a task; duplicate-check first, then call Agent Hub for assessment."""
    logger.info("Starting idea triage", task_id=task_id, project_id=project_id)
    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for triage", task_id=task_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    # Skip triage for tasks that already have an approved plan
    spirit = get_task_spirit(task_id)
    if spirit and str(spirit.get("plan_status", "")).lower() == "approved":
        logger.info("Skipping triage — plan already approved", task_id=task_id)
        return {"task_id": task_id, "status": "completed", "result": {"status": "READY"}}

    title = task.get("title", "")
    description = task.get("description", "")
    dup_result = _check_duplicate(task_id, project_id, title, description)
    if dup_result:
        return dup_result

    prompt = _TRIAGE_PROMPT_TEMPLATE.format(title=title, description=description or "(no description provided)")
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug=AGENT_TRIAGER.replace("agent:", ""),
        )
        triage_result = _parse_triage_response(response.content)
        _process_triage_result(task_id, triage_result)
        return {"task_id": task_id, "status": "completed", "result": triage_result}
    except Exception as e:
        logger.warning("Triage failed", task_id=task_id, error=str(e))
        return {"task_id": task_id, "status": "error", "message": str(e)}
