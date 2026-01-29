"""AI Review Celery task for pull request validation.

This task implements the AI review gate for the git management workflow.
It runs when a task transitions to ai_reviewing status after PR creation.

Review Pipeline:
1. Test execution (pytest with coverage threshold)
2. Lint check (pre-commit hooks)
3. Type check (mypy)
4. Code quality scan (Claude Opus 4.5)
5. UI review (Gemini 3 Pro for frontend changes)
6. Acceptance criteria verification
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app
from app.logging_config import get_logger
from app.storage import log_task_event
from app.storage import tasks as task_store

from .ai_review_checks import (
    _run_breaking_change_detection,
    _run_code_quality_review,
    _run_mypy,
    _run_precommit,
    _run_pytest,
    _run_security_risk_classification,
    _run_ui_review,
    _verify_acceptance_criteria,
)
from .ai_review_models import ReviewResult, ReviewVerdict, RiskLevel
from .ai_review_utils import (
    _auto_merge_pr,
    _get_project_path,
    _notify_human_review_needed,
    _should_escalate_for_security,
)

logger = get_logger(__name__)


@celery_app.task(
    name="summitflow.review_pull_request",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def review_pull_request(
    self: Any,
    task_id: str,
    pr_url: str | None = None,
) -> dict[str, Any]:
    """Review a pull request for a task.

    Runs the full review pipeline:
    1. Test execution (pytest)
    2. Lint check (pre-commit)
    3. Type check (mypy)
    4. Code quality scan (Opus)
    5. UI review (Gemini) if frontend changes
    6. Acceptance criteria verification

    Args:
        task_id: Task ID to review
        pr_url: Optional PR URL (for reference)

    Returns:
        ReviewResult as dict with overall verdict and check details
    """
    logger.info("review_pull_request_start", task_id=task_id, pr_url=pr_url)

    try:
        # Get task
        task = task_store.get_task(task_id)
        if not task:
            return ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Task {task_id} not found",
                issues=[f"Task {task_id} not found"],
            ).to_dict()

        # Verify task is in ai_reviewing status
        if task.get("status") != "ai_reviewing":
            logger.warning(
                "task_not_in_review",
                task_id=task_id,
                status=task.get("status"),
            )
            return ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Task not in ai_reviewing status (current: {task.get('status')})",
                issues=["Task must be in ai_reviewing status for review"],
            ).to_dict()

        project_path = _get_project_path(task)
        checks: dict[str, Any] = {}
        all_issues: list[str] = []
        all_suggestions: list[str] = []

        # Step 1: Security risk classification (runs first, can short-circuit)
        logger.info("running_security_risk_classification", task_id=task_id)
        checks["security_risk"] = _run_security_risk_classification(task, project_path)
        risk_level = RiskLevel(checks["security_risk"].get("risk_level", "low"))

        # High-risk changes short-circuit to human review immediately
        if checks["security_risk"].get("status") == "escalate":
            escalation_reason = checks["security_risk"].get(
                "escalation_reason", "High-risk changes"
            )
            logger.info("security_gate_escalation", task_id=task_id, reason=escalation_reason)

            security_reasons: list[str] = checks["security_risk"].get("reasons", [])
            result = ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Security gate: {escalation_reason}",
                checks=checks,
                issues=[f"SECURITY GATE: {escalation_reason}", *security_reasons],
                risk_level=risk_level,
            )

            # Update task and escalate to human review
            task_store.update_task(task_id, review_result=result.to_dict())
            task_store.update_task_status(task_id, "human_review")
            _notify_human_review_needed(task_id, escalation_reason)

            return result.to_dict()

        # Step 2: Run remaining checks
        logger.info("running_pytest", task_id=task_id)
        checks["pytest"] = _run_pytest(project_path)
        if checks["pytest"].get("status") == "fail":
            all_issues.append("pytest: Tests failed")

        # Step 3: Breaking change detection (runs after pytest to include test results)
        logger.info("running_breaking_change_detection", task_id=task_id)
        checks["breaking_change"] = _run_breaking_change_detection(
            task, project_path, checks["pytest"]
        )

        # Breaking changes escalate to human review
        if checks["breaking_change"].get("status") == "escalate":
            bc_reasons = checks["breaking_change"].get("reasons", [])
            escalation_reason = f"Breaking changes detected: {'; '.join(bc_reasons)}"
            logger.info("breaking_change_escalation", task_id=task_id, reason=escalation_reason)

            result = ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Breaking change gate: {escalation_reason}",
                checks=checks,
                issues=[f"BREAKING CHANGE: {r}" for r in bc_reasons],
                risk_level=risk_level,
            )

            # Update task and escalate to human review
            task_store.update_task(task_id, review_result=result.to_dict())
            task_store.update_task_status(task_id, "human_review")
            _notify_human_review_needed(task_id, escalation_reason)

            return result.to_dict()

        logger.info("running_precommit", task_id=task_id)
        checks["precommit"] = _run_precommit(project_path)
        if checks["precommit"].get("status") == "fail":
            all_issues.append("pre-commit: Lint/format issues")

        logger.info("running_mypy", task_id=task_id)
        checks["mypy"] = _run_mypy(project_path)
        if checks["mypy"].get("status") == "fail":
            all_issues.append("mypy: Type errors")

        logger.info("running_code_quality", task_id=task_id)
        checks["code_quality"] = _run_code_quality_review(task, project_path)
        if checks["code_quality"].get("status") == "fail":
            all_issues.extend(checks["code_quality"].get("issues", []))
            all_suggestions.extend(checks["code_quality"].get("suggestions", []))

        logger.info("running_ui_review", task_id=task_id)
        checks["ui_review"] = _run_ui_review(task, project_path)
        if checks["ui_review"].get("status") == "fail":
            all_issues.extend(checks["ui_review"].get("issues", []))
            all_suggestions.extend(checks["ui_review"].get("suggestions", []))

        logger.info("verifying_criteria", task_id=task_id)
        checks["acceptance_criteria"] = _verify_acceptance_criteria(task)
        if checks["acceptance_criteria"].get("status") == "fail":
            missing = checks["acceptance_criteria"].get("missing", [])
            all_issues.append(f"Unverified criteria: {len(missing)}")

        # Check for security concerns that require immediate escalation
        security_escalation = _should_escalate_for_security(checks, all_issues)

        # Determine overall verdict
        failed_checks = [name for name, result in checks.items() if result.get("status") == "fail"]
        error_checks = [name for name, result in checks.items() if result.get("status") == "error"]

        if security_escalation:
            # Security concerns bypass retry - escalate immediately
            verdict = ReviewVerdict.FAIL
            summary = f"Security concerns detected: {security_escalation}"
            all_issues.insert(0, f"SECURITY: {security_escalation}")
        elif error_checks:
            # Errors are retriable
            try:
                raise self.retry(
                    exc=Exception(f"Check errors: {error_checks}"),
                    countdown=60 * (2**self.request.retries),  # Exponential backoff
                )
            except self.MaxRetriesExceededError:
                verdict = ReviewVerdict.FAIL
                summary = f"Review failed after {self.request.retries + 1} attempts"
        elif failed_checks:
            verdict = ReviewVerdict.NEEDS_FIX
            summary = f"Review found issues in: {', '.join(failed_checks)}"
        else:
            verdict = ReviewVerdict.PASS
            summary = "All checks passed"

        result = ReviewResult(
            verdict=verdict,
            summary=summary,
            checks=checks,
            issues=all_issues,
            suggestions=all_suggestions,
            risk_level=risk_level,
        )

        # Update task with review result
        task_store.update_task(task_id, review_result=result.to_dict())

        # Handle verdict transitions
        if verdict == ReviewVerdict.PASS:
            # Auto-approve: merge PR and transition to completed
            if pr_url:
                _auto_merge_pr(task_id, pr_url, project_path)
            task_store.update_task_status(task_id, "completed")
            logger.info("review_passed", task_id=task_id)
        elif verdict == ReviewVerdict.NEEDS_FIX:
            # Needs work: keep in ai_reviewing for now, log issues
            log_task_event(
                task_id,
                f"AI Review needs fixes: {', '.join(all_issues[:3])}",
            )
            logger.info("review_needs_fix", task_id=task_id, issues=len(all_issues))
        else:
            # Failed: escalate to human review
            task_store.update_task_status(task_id, "human_review")
            _notify_human_review_needed(task_id, summary)
            logger.info("review_escalated", task_id=task_id)

        return result.to_dict()

    except Exception as e:
        logger.error("review_pull_request_error", task_id=task_id, error=str(e))
        return ReviewResult(
            verdict=ReviewVerdict.FAIL,
            summary=f"Review error: {e}",
            issues=[str(e)],
        ).to_dict()
