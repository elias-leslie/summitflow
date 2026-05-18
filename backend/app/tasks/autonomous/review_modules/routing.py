"""Review verdict routing and escalation handling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage import log_task_event
from ....storage import tasks as task_store
from ....storage.notifications import (
    create_task_completion_notification,
    create_task_failure_notification,
)
from .._project_resolution import resolve_task_project_id
from ..exec_modules.ah_events import emit_review_verdict, emit_task_transition
from .actions import create_fix_subtask, handle_plan_defect, run_qa_loop

logger = get_logger(__name__)
STATUS_COMPLETED = "completed"
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"
AGENT_SUPERVISOR = "supervisor"
VERDICT_APPROVED = "APPROVED"
VERDICT_NEEDS_FIX = "NEEDS_FIX"
VERDICT_PLAN_DEFECT = "PLAN_DEFECT"
DECISION_APPROVE = "approve"
DECISION_FIX = "fix"


def _get_project_id(task_id: str, project_id: str | None = None) -> str:
    """Resolve project scope, skipping DB fetch when project_id is provided."""
    if project_id:
        return project_id
    return resolve_task_project_id(task_store.get_task(task_id))


def _task_status(task_id: str) -> str | None:
    task = task_store.get_task(task_id)
    if not task:
        return None
    return str(task.get("status") or "")


def _set_followup_status(task_id: str, *, fallback: str) -> str:
    """Reopen completed tasks safely when review finds more work.

    Completed tasks may not transition directly back to running/failed. Reopen them
    to pending so the control plane can schedule follow-up work without raising an
    invalid-transition error.
    """
    target_status = STATUS_PENDING if _task_status(task_id) == STATUS_COMPLETED else fallback
    task_store.update_task_status(task_id, target_status)
    return target_status


def _send_notification(task_id: str, project_id: str, fn: Callable[..., object], **kwargs: Any) -> None:
    try:
        task = task_store.get_task(task_id)
        title = task.get("title", "Unknown") if task else "Unknown"
        sessions = task_store.get_agent_hub_sessions(task_id)
        fn(project_id=project_id, task_id=task_id, task_title=title,
           agent_hub_session_ids=sessions or None, **kwargs)
    except Exception:
        logger.exception("Failed to send notification", task_id=task_id)


def supervisor_resolve_escalation(task_id: str, review_summary: str, project_id: str) -> str:
    """Supervisor triages an ESCALATE verdict. Returns 'fix', 'approve', or 'block'."""
    prompt = (f"AI reviewer escalated task {task_id}.\nReviewer said: {review_summary[:500]}\n\n"
              "Options:\n- FIX: Create a fix subtask\n- APPROVE: Override and accept\n- BLOCK: Park the task\nReply FIX, APPROVE, or BLOCK.")
    try:
        upper = get_sync_client().complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug=AGENT_SUPERVISOR,
            project_id=project_id,
        ).content.upper()
        if "APPROVE" in upper:
            return DECISION_APPROVE
        return DECISION_FIX if "FIX" in upper else "block"
    except Exception:
        logger.warning("Supervisor escalation resolution failed, defaulting to block", exc_info=True)
        return "block"


def route_based_on_verdict(task_id: str, complexity: str, review_result: Mapping[str, Any]) -> None:
    """Route task based on AI review verdict."""
    verdict = str(review_result.get("verdict", "")).upper()
    concerns = [str(c) for c in review_result.get("concerns", [])]
    emit_review_verdict(task_id, verdict, concerns or None)
    if verdict == VERDICT_APPROVED:
        _handle_approved(task_id, complexity)
    elif verdict in (VERDICT_NEEDS_FIX, "REJECT", "REJECTED"):
        _handle_needs_fix(task_id, review_result)
    elif verdict == VERDICT_PLAN_DEFECT:
        handle_plan_defect(task_id, review_result)
        _set_followup_status(task_id, fallback=STATUS_RUNNING)
        log_task_event(task_id, "AI Review: PLAN_DEFECT - Added fix step with correct verification")
        logger.info("Plan defect detected, added fix step", task_id=task_id)
    else:
        _handle_escalation(task_id, review_result)


def _complete_after_review(task_id: str, project_id: str, *, detail: str) -> None:
    """Mark a task completed, run checkpoint cleanup, and notify."""
    from ..cleanup.checkpoint_cleanup import cleanup_task_checkpoint

    task_store.update_task_status(task_id, STATUS_COMPLETED)
    cleanup_result = cleanup_task_checkpoint(task_id, delete_branch=False, project_id=project_id)
    if cleanup_result.get("status") != "cleaned":
        reason = str(cleanup_result.get("reason") or cleanup_result.get("error") or "unknown")
        log_task_event(task_id, f"Manual cleanup review needed: {reason}")
    if _task_status(task_id) == STATUS_COMPLETED:
        _send_notification(task_id, project_id, create_task_completion_notification, detail=detail)


def _handle_approved(task_id: str, complexity: str) -> None:
    project_id = _get_project_id(task_id)
    emit_task_transition(task_id, STATUS_COMPLETED, "APPROVED")
    log_task_event(task_id, f"AI Review: APPROVED ({complexity})")
    logger.info("QA approved", task_id=task_id, complexity=complexity)
    _complete_after_review(task_id, project_id, detail="QA approval.")


def _handle_needs_fix(task_id: str, review_result: Mapping[str, Any]) -> None:
    from ....storage.projects import get_project_root_path

    concerns = [str(c) for c in review_result.get("concerns", [])]
    verdict = str(review_result.get("verdict", VERDICT_NEEDS_FIX))
    project_id = _get_project_id(task_id)
    if not concerns:
        log_task_event(task_id, f"AI Review: {verdict} with no concerns - treating as APPROVED")
        logger.info("QA no concerns", task_id=task_id)
        _complete_after_review(task_id, project_id, detail="QA passed with no concerns.")
        return
    project_root = get_project_root_path(project_id)
    if project_root:
        _set_followup_status(task_id, fallback=STATUS_RUNNING)
        log_task_event(task_id, f"AI Review: {verdict} - Starting QA loop")
        loop_result = run_qa_loop(task_id, project_id, review_result, str(project_root))
        if loop_result == VERDICT_APPROVED:
            task = task_store.get_task(task_id)
            _handle_approved(task_id, str(task.get("complexity", "STANDARD")) if task else "STANDARD")
            return
        if loop_result == "ESCALATE":
            _handle_escalation(task_id, review_result)
            return
    create_fix_subtask(task_id, review_result)
    followup_status = _set_followup_status(task_id, fallback=STATUS_RUNNING)
    log_task_event(task_id, f"AI Review: {verdict} - QA loop exhausted, created fix subtask. Issues: {concerns}")
    logger.info("QA loop exhausted, fix subtask created", task_id=task_id, followup_status=followup_status)


def _handle_escalation(task_id: str, review_result: Mapping[str, Any]) -> None:
    project_id = _get_project_id(task_id)
    summary = str(review_result.get("summary", "Unknown issue"))
    decision = supervisor_resolve_escalation(task_id, summary, project_id)
    if decision == DECISION_APPROVE:
        log_task_event(task_id, "AI Review: ESCALATE - Supervisor approved")
        logger.info("Escalation overridden by supervisor", task_id=task_id)
        _complete_after_review(task_id, project_id, detail="Supervisor override — approved.")
        return
    if decision == DECISION_FIX:
        create_fix_subtask(task_id, {"concerns": [summary[:500]], "recommendation": summary[:500]})
        followup_status = _set_followup_status(task_id, fallback=STATUS_RUNNING)
        log_task_event(task_id, "AI Review: ESCALATE - Supervisor created fix subtask")
        logger.info("Escalation resolved with fix subtask", task_id=task_id, followup_status=followup_status)
        return
    followup_status = _set_followup_status(task_id, fallback=STATUS_FAILED)
    emit_task_transition(task_id, followup_status, f"Supervisor blocked: {summary[:100]}")
    log_task_event(task_id, f"AI Review: ESCALATE - Blocked. {summary[:200]}")
    logger.info("QA escalated, blocked by supervisor", task_id=task_id, followup_status=followup_status)
    if followup_status == STATUS_FAILED:
        _send_notification(task_id, project_id, create_task_failure_notification,
                           error_message=f"Supervisor blocked this task: {summary[:200]}")
