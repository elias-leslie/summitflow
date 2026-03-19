"""Review verdict routing and escalation handling."""

from __future__ import annotations

from collections.abc import Callable

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage import agent_configs, log_task_event
from ....storage import tasks as task_store
from ....storage.notifications import (
    create_task_completion_notification,
    create_task_failure_notification,
)
from .._project_resolution import resolve_task_project_id
from ..cleanup.merge_types import MergeResult
from ..exec_modules.ah_events import emit_review_verdict, emit_task_transition
from .actions import auto_merge, create_fix_subtask, handle_plan_defect, run_qa_loop

logger = get_logger(__name__)
STATUS_COMPLETED = "completed"
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


def _maybe_auto_merge(task_id: str, project_id: str) -> MergeResult | None:
    if not agent_configs.get_auto_merge_enabled(project_id):
        return None
    return auto_merge(task_id)


def _task_status(task_id: str) -> str | None:
    task = task_store.get_task(task_id)
    if not task:
        return None
    return str(task.get("status") or "")


def _apply_auto_merge_status(task_id: str, merge_result: dict[str, object] | None) -> str:
    if merge_result is None:
        task_store.update_task_status(task_id, STATUS_COMPLETED)
        return "ready for manual merge"

    merge_status = str(merge_result.get("status") or "blocked")
    if merge_status in {"merged", "skipped"}:
        return "auto-merged"
    if merge_status == "conflicted":
        return "merge conflicted"
    if merge_status == "rolled_back":
        return "auto-merge rolled back"
    return "auto-merge failed"


def _send_notification(task_id: str, project_id: str, fn: Callable[..., None], **kwargs: str) -> None:
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
              "Options:\n- FIX: Create a fix subtask\n- APPROVE: Override and auto-merge\n- BLOCK: Park the task\nReply FIX, APPROVE, or BLOCK.")
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


def route_based_on_verdict(task_id: str, complexity: str, review_result: dict[str, str | list[str]]) -> None:
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
        task_store.update_task_status(task_id, STATUS_RUNNING)
        log_task_event(task_id, "AI Review: PLAN_DEFECT - Added fix step with correct verification")
        logger.info("Plan defect detected, added fix step", task_id=task_id)
    else:
        _handle_escalation(task_id, review_result)


def _handle_approved(task_id: str, complexity: str) -> None:
    from ..cleanup.worktree_cleanup import cleanup_task_worktree
    from ..exec_modules.completion_status import wake_persona

    project_id = _get_project_id(task_id)
    merge_result = _maybe_auto_merge(task_id, project_id)
    label = _apply_auto_merge_status(task_id, merge_result)
    current_status = _task_status(task_id) or STATUS_COMPLETED
    if merge_result is None:
        cleanup_result = cleanup_task_worktree(task_id, delete_branch=False, project_id=project_id)
        if cleanup_result.get("status") == "cleaned":
            label = "Ready for manual merge (worktree cleaned)"
        else:
            reason = str(cleanup_result.get("reason") or cleanup_result.get("error") or "unknown")
            log_task_event(task_id, f"Manual cleanup review needed: {reason}")
            wake_persona(
                task_id,
                project_id,
                "cleanup_needed",
                f"Approved task {task_id} needs cleanup review: {reason}. Branch is kept for manual merge.",
            )
        current_status = STATUS_COMPLETED
    emit_task_transition(task_id, current_status, f"APPROVED — {label}")
    log_task_event(task_id, f"AI Review: APPROVED - {label} ({complexity})")
    logger.info("QA approved", task_id=task_id, complexity=complexity, merge_status=label)
    if _task_status(task_id) == STATUS_COMPLETED:
        _send_notification(task_id, project_id, create_task_completion_notification, detail=f"{label} after QA approval.")


def _handle_needs_fix(task_id: str, review_result: dict[str, str | list[str]]) -> None:
    from ..cleanup.worktree_cleanup import cleanup_task_worktree
    from ..exec_modules.completion_status import wake_persona

    concerns = review_result.get("concerns", [])
    verdict = review_result.get("verdict", VERDICT_NEEDS_FIX)
    project_id = _get_project_id(task_id)
    if not concerns:
        log_task_event(task_id, f"AI Review: {verdict} with no concerns - treating as APPROVED")
        merge_result = _maybe_auto_merge(task_id, project_id)
        merge_label = _apply_auto_merge_status(task_id, merge_result)
        if merge_result is None:
            cleanup_result = cleanup_task_worktree(task_id, delete_branch=False, project_id=project_id)
            if cleanup_result.get("status") != "cleaned":
                reason = str(cleanup_result.get("reason") or cleanup_result.get("error") or "unknown")
                log_task_event(task_id, f"Manual cleanup review needed: {reason}")
                wake_persona(
                    task_id,
                    project_id,
                    "cleanup_needed",
                    f"Approved task {task_id} needs cleanup review: {reason}. Branch is kept for manual merge.",
                )
        logger.info("QA no concerns", task_id=task_id, merge_status=(merge_result or {}).get("status"))
        if _task_status(task_id) == STATUS_COMPLETED:
            _send_notification(task_id, project_id, create_task_completion_notification, detail=f"QA passed with no concerns ({merge_label}).")
        return
    from app.services.worktree import get_task_worktree
    worktree = get_task_worktree(task_id, project_id)
    if worktree and worktree.path:
        log_task_event(task_id, f"AI Review: {verdict} - Starting QA loop")
        loop_result = run_qa_loop(task_id, project_id, review_result, str(worktree.path))
        if loop_result == VERDICT_APPROVED:
            task = task_store.get_task(task_id)
            _handle_approved(task_id, str(task.get("complexity", "STANDARD")) if task else "STANDARD")
            return
        if loop_result == "ESCALATE":
            _handle_escalation(task_id, review_result)
            return
    create_fix_subtask(task_id, review_result)
    task_store.update_task_status(task_id, STATUS_RUNNING)
    log_task_event(task_id, f"AI Review: {verdict} - QA loop exhausted, created fix subtask. Issues: {concerns}")
    logger.info("QA loop exhausted, fix subtask created", task_id=task_id)


def _handle_escalation(task_id: str, review_result: dict[str, str | list[str]]) -> None:
    project_id = _get_project_id(task_id)
    summary = str(review_result.get("summary", "Unknown issue"))
    decision = supervisor_resolve_escalation(task_id, summary, project_id)
    if decision == DECISION_APPROVE:
        merge_result = _maybe_auto_merge(task_id, project_id)
        merge_label = _apply_auto_merge_status(task_id, merge_result)
        log_task_event(task_id, f"AI Review: ESCALATE - Supervisor approved, {merge_label}")
        logger.info("Escalation overridden by supervisor", task_id=task_id, merge_status=merge_label)
        if _task_status(task_id) == STATUS_COMPLETED:
            _send_notification(task_id, project_id, create_task_completion_notification, detail="Supervisor override — approved.")
        return
    if decision == DECISION_FIX:
        create_fix_subtask(task_id, {"concerns": [summary[:500]], "recommendation": summary[:500]})
        task_store.update_task_status(task_id, STATUS_RUNNING)
        log_task_event(task_id, "AI Review: ESCALATE - Supervisor created fix subtask")
        logger.info("Escalation resolved with fix subtask", task_id=task_id)
        return
    task_store.update_task_status(task_id, STATUS_FAILED)
    emit_task_transition(task_id, STATUS_FAILED, f"Supervisor blocked: {summary[:100]}")
    log_task_event(task_id, f"AI Review: ESCALATE - Blocked. {summary[:200]}")
    logger.info("QA escalated, blocked by supervisor", task_id=task_id)
    _send_notification(task_id, project_id, create_task_failure_notification,
                       error_message=f"Supervisor blocked this task: {summary[:200]}")
