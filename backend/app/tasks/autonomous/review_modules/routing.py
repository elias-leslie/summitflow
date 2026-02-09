"""Review verdict routing and escalation handling."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage import log_task_event
from ....storage import tasks as task_store
from .actions import auto_merge, create_fix_subtask, handle_plan_defect

logger = get_logger(__name__)


def supervisor_resolve_escalation(
    task_id: str, review_summary: str, project_id: str
) -> str:
    """Supervisor triages an ESCALATE verdict.

    Args:
        task_id: Task ID being reviewed
        review_summary: Summary from reviewer
        project_id: Project ID

    Returns:
        Decision: 'fix', 'approve', or 'block'
    """
    prompt = (
        f"AI reviewer escalated task {task_id}.\n"
        f"Reviewer said: {review_summary[:500]}\n\n"
        f"Options:\n"
        f"- FIX: Create a fix subtask to address the concern\n"
        f"- APPROVE: Override and auto-merge anyway\n"
        f"- BLOCK: Park the task\n"
        f"Reply FIX, APPROVE, or BLOCK."
    )
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id,
        )
        upper = response.content.upper()
        if "APPROVE" in upper:
            return "approve"
        if "FIX" in upper:
            return "fix"
        return "block"
    except Exception:
        return "block"


def route_based_on_verdict(
    task_id: str,
    complexity: str,
    review_result: dict[str, Any],
) -> None:
    """Route task based on AI review verdict.

    Verdicts:
    - APPROVED: Always auto-merge
    - NEEDS_FIX with no concerns: Treat as APPROVED, auto-merge
    - NEEDS_FIX with concerns: Create fix subtask, retry execution
    - PLAN_DEFECT: Add fix step, mark original as defect, retry
    - ESCALATE/unknown: Supervisor triage → approve, fix, or block

    Args:
        task_id: Task ID being reviewed
        complexity: Task complexity level
        review_result: Parsed review result with verdict
    """
    verdict = review_result.get("verdict", "").upper()

    if verdict == "APPROVED":
        _handle_approved(task_id, complexity)
    elif verdict in ("NEEDS_FIX", "REJECT", "REJECTED"):
        _handle_needs_fix(task_id, review_result)
    elif verdict == "PLAN_DEFECT":
        _handle_plan_defect_verdict(task_id, review_result)
    else:
        _handle_escalation(task_id, review_result)


def _handle_approved(task_id: str, complexity: str) -> None:
    """Handle APPROVED verdict."""
    auto_merge(task_id)
    task_store.update_task_status(task_id, "completed")
    log_task_event(
        task_id,
        f"AI Review: APPROVED - Auto-merged ({complexity})",
    )
    logger.info(
        "QA approved, auto-merged",
        task_id=task_id,
        complexity=complexity,
    )


def _handle_needs_fix(task_id: str, review_result: dict[str, Any]) -> None:
    """Handle NEEDS_FIX verdict."""
    concerns = review_result.get("concerns", [])
    verdict = review_result.get("verdict", "NEEDS_FIX")

    if not concerns:
        log_task_event(
            task_id,
            f"AI Review: {verdict} with no concerns - treating as APPROVED",
        )
        auto_merge(task_id)
        task_store.update_task_status(task_id, "completed")
        logger.info("QA no concerns, auto-merged", task_id=task_id)
    else:
        create_fix_subtask(task_id, review_result)
        task_store.update_task_status(task_id, "running")
        log_task_event(
            task_id,
            f"AI Review: {verdict} - Created fix subtask. Issues: {concerns}",
        )
        logger.info("QA needs fix, returning to execution", task_id=task_id)


def _handle_plan_defect_verdict(
    task_id: str, review_result: dict[str, Any]
) -> None:
    """Handle PLAN_DEFECT verdict."""
    handle_plan_defect(task_id, review_result)
    task_store.update_task_status(task_id, "running")
    log_task_event(
        task_id,
        "AI Review: PLAN_DEFECT - Added fix step with correct verification",
    )
    logger.info("Plan defect detected, added fix step", task_id=task_id)


def _handle_escalation(task_id: str, review_result: dict[str, Any]) -> None:
    """Handle ESCALATE or unknown verdict."""
    task = task_store.get_task(task_id)
    project_id = task.get("project_id", "summitflow") if task else "summitflow"
    summary = review_result.get("summary", "Unknown issue")
    decision = supervisor_resolve_escalation(task_id, summary, project_id)

    if decision == "approve":
        auto_merge(task_id)
        task_store.update_task_status(task_id, "completed")
        log_task_event(
            task_id,
            "AI Review: ESCALATE - Supervisor approved, auto-merged",
        )
        logger.info(
            "Escalation overridden by supervisor, auto-merged", task_id=task_id
        )
    elif decision == "fix":
        fix_review = {
            "concerns": [summary[:500]],
            "recommendation": summary[:500],
        }
        create_fix_subtask(task_id, fix_review)
        task_store.update_task_status(task_id, "running")
        log_task_event(
            task_id,
            "AI Review: ESCALATE - Supervisor created fix subtask",
        )
        logger.info("Escalation resolved with fix subtask", task_id=task_id)
    else:
        task_store.update_task_status(task_id, "blocked")
        log_task_event(
            task_id,
            f"AI Review: ESCALATE - Blocked. {summary[:200]}",
        )
        logger.info("QA escalated, blocked by supervisor", task_id=task_id)
