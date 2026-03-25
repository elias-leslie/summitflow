"""AI Review task for pull request validation.

Implements the AI review gate for git workflow. Runs when task transitions to running status for review. Pipeline: pytest, pre-commit, types, code quality (Opus), UI review (Gemini), step verification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.logging_config import get_logger
from app.storage import log_task_event
from app.storage import tasks as task_store

from .ai_review_checks import (
    _run_breaking_change_detection,
    _run_code_quality_review,
    _run_precommit,
    _run_pytest,
    _run_security_risk_classification,
    _run_types,
    _run_ui_review,
    _verify_step_completion,
)
from .ai_review_models import ReviewResult, ReviewVerdict, RiskLevel
from .ai_review_utils import (
    _auto_merge_pr,
    _get_project_path,
    _notify_supervisor_review_needed,
    _should_escalate_for_security,
)

logger = get_logger(__name__)


def _handle_escalation(
    task_id: str, checks: dict[str, Any], escalation_type: str, reason: str, issues: list[str], risk_level: RiskLevel
) -> dict[str, Any]:
    logger.info("%s_escalation", escalation_type, task_id=task_id, reason=reason)
    result = ReviewResult(verdict=ReviewVerdict.FAIL, summary=f"{escalation_type}: {reason}", checks=checks, issues=issues, risk_level=risk_level)
    task_store.update_task(task_id, review_result=result.to_dict())
    task_store.update_task_status(task_id, "failed")
    _notify_supervisor_review_needed(task_id, reason)
    return result.to_dict()


def _collect_check_issues(
    check_name: str, check_result: dict[str, Any], simple_msg: str | None, has_details: bool
) -> tuple[list[str], list[str]]:
    """Extract issues and suggestions from a failed check result."""
    if simple_msg:
        return [simple_msg], []
    if has_details:
        return check_result.get("issues", []), check_result.get("suggestions", [])
    if check_name == "step_completion":
        return [f"Incomplete steps: {len(check_result.get('missing', []))}"], []
    return [], []


def _run_standard_checks(task: dict[str, Any], project_path: Path, checks: dict[str, Any]) -> tuple[list[str], list[str]]:
    all_issues: list[str] = []
    all_suggestions: list[str] = []
    task_id = task.get("id")
    check_configs = [
        ("precommit", lambda: _run_precommit(project_path), "pre-commit: Lint/format issues", False),
        ("types", lambda: _run_types(project_path), "types: Type errors", False),
        ("code_quality", lambda: _run_code_quality_review(task, project_path), None, True),
        ("ui_review", lambda: _run_ui_review(task, project_path), None, True),
        ("step_completion", lambda: _verify_step_completion(task), None, False),
    ]
    for check_name, check_fn, simple_msg, has_details in check_configs:
        logger.info("running_%s", check_name, task_id=task_id)
        checks[check_name] = check_fn()
        if checks[check_name].get("status") != "fail":
            continue
        issues, suggestions = _collect_check_issues(check_name, checks[check_name], simple_msg, has_details)
        all_issues.extend(issues)
        all_suggestions.extend(suggestions)
    return all_issues, all_suggestions


def _determine_verdict(checks: dict[str, Any], all_issues: list[str]) -> tuple[ReviewVerdict, str]:
    security_escalation = _should_escalate_for_security(checks, all_issues)
    failed_checks = [name for name, result in checks.items() if result.get("status") == "fail"]
    error_checks = [name for name, result in checks.items() if result.get("status") == "error"]
    if security_escalation:
        all_issues.insert(0, f"SECURITY: {security_escalation}")
        return ReviewVerdict.FAIL, f"Security concerns detected: {security_escalation}"
    if error_checks:
        raise RuntimeError(f"Check errors: {error_checks}")
    if failed_checks:
        return ReviewVerdict.NEEDS_FIX, f"Review found issues in: {', '.join(failed_checks)}"
    return ReviewVerdict.PASS, "All checks passed"


def _apply_pass_verdict(task_id: str, pr_url: str | None, task: dict[str, Any] | None = None) -> None:
    if pr_url:
        if task is None:
            logger.warning("apply_pass_verdict_no_task", task_id=task_id, reason="task not found; skipping auto-merge")
        else:
            _auto_merge_pr(task_id, pr_url, _get_project_path(task))
    task_store.update_task_status(task_id, "completed")
    logger.info("review_passed", task_id=task_id)


def _apply_verdict(task_id: str, pr_url: str | None, verdict: ReviewVerdict, summary: str, all_issues: list[str], task: dict[str, Any] | None = None) -> None:
    if verdict == ReviewVerdict.PASS:
        _apply_pass_verdict(task_id, pr_url, task)
    elif verdict == ReviewVerdict.NEEDS_FIX:
        log_task_event(task_id, f"AI Review needs fixes: {', '.join(all_issues[:3])}")
        logger.info("review_needs_fix", task_id=task_id, issues=len(all_issues))
    else:
        task_store.update_task_status(task_id, "failed")
        _notify_supervisor_review_needed(task_id, summary)
        logger.info("review_escalated", task_id=task_id)


def _do_review(task_id: str, task: dict[str, Any], pr_url: str | None) -> dict[str, Any]:
    project_path = _get_project_path(task)
    checks: dict[str, Any] = {}
    logger.info("running_security_risk_classification", task_id=task_id)
    checks["security_risk"] = _run_security_risk_classification(task, project_path)
    risk_level = RiskLevel(checks["security_risk"].get("risk_level", "low"))
    if checks["security_risk"].get("status") == "escalate":
        reason = checks["security_risk"].get("escalation_reason", "High-risk changes")
        reasons = checks["security_risk"].get("reasons", [])
        return _handle_escalation(task_id, checks, "Security gate", reason, [f"SECURITY GATE: {reason}", *reasons], risk_level)
    logger.info("running_pytest", task_id=task_id)
    checks["pytest"] = _run_pytest(project_path)
    all_issues = ["pytest: Tests failed"] if checks["pytest"].get("status") == "fail" else []
    logger.info("running_breaking_change_detection", task_id=task_id)
    checks["breaking_change"] = _run_breaking_change_detection(task, project_path, checks["pytest"])
    if checks["breaking_change"].get("status") == "escalate":
        bc_reasons = checks["breaking_change"].get("reasons", [])
        return _handle_escalation(task_id, checks, "Breaking change gate", f"Breaking changes detected: {'; '.join(bc_reasons)}", [f"BREAKING CHANGE: {r}" for r in bc_reasons], risk_level)
    issues, suggestions = _run_standard_checks(task, project_path, checks)
    all_issues.extend(issues)
    verdict, summary = _determine_verdict(checks, all_issues)
    result = ReviewResult(verdict=verdict, summary=summary, checks=checks, issues=all_issues, suggestions=suggestions, risk_level=risk_level)
    task_store.update_task(task_id, review_result=result.to_dict())
    _apply_verdict(task_id, pr_url, verdict, summary, all_issues, task)
    return result.to_dict()


def _validate_task_for_review(task_id: str, task: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return an error result dict if the task is invalid, else None."""
    if not task:
        return ReviewResult(verdict=ReviewVerdict.FAIL, summary=f"Task {task_id} not found", issues=[f"Task {task_id} not found"]).to_dict()
    if task.get("status") != "running":
        logger.warning("task_not_in_review", task_id=task_id, status=task.get("status"))
        return ReviewResult(verdict=ReviewVerdict.FAIL, summary=f"Task not in running status (current: {task.get('status')})", issues=["Task must be in running status for review"]).to_dict()
    return None


def review_pull_request(task_id: str, pr_url: str | None = None) -> dict[str, Any]:
    logger.info("review_pull_request_start", task_id=task_id, pr_url=pr_url)
    task = task_store.get_task(task_id)
    error = _validate_task_for_review(task_id, task)
    if error is not None:
        return error
    assert task is not None
    try:
        return _do_review(task_id, task, pr_url)
    except Exception as e:
        logger.error("review_pull_request_error", task_id=task_id, error=str(e))
        return ReviewResult(verdict=ReviewVerdict.FAIL, summary=f"Review error: {e}", issues=[str(e)]).to_dict()
