"""Utility functions for AI review task."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.logging_config import get_logger
from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.notifications import create_notification

from .ai_review_constants import ARCHITECTURE_KEYWORDS, SECURITY_KEYWORDS

logger = get_logger(__name__)


def _should_escalate_for_security(
    checks: dict[str, Any],
    issues: list[str],
) -> str | None:
    """Check if issues require immediate escalation for security concerns.

    Args:
        checks: All check results
        issues: Accumulated issues list

    Returns:
        Escalation reason string if should escalate, None otherwise
    """
    # Check code quality review for security-related rejections
    code_quality = checks.get("code_quality", {})
    if code_quality.get("verdict") == "REJECT":
        summary = code_quality.get("summary", "").lower()
        cq_issues = code_quality.get("issues", [])

        # Check for security keywords in summary or issues
        all_text = summary + " " + " ".join(str(i).lower() for i in cq_issues)

        for keyword in SECURITY_KEYWORDS:
            if keyword in all_text:
                return f"Security issue: {keyword} detected in code review"

        for keyword in ARCHITECTURE_KEYWORDS:
            if keyword in all_text:
                return f"Architectural issue: {keyword}"

    # Check accumulated issues for security patterns
    issues_text = " ".join(str(i).lower() for i in issues)
    for keyword in SECURITY_KEYWORDS:
        if keyword in issues_text:
            return f"Security concern: {keyword}"

    return None


def _notify_supervisor_review_needed(task_id: str, reason: str) -> None:
    """Create notification for supervisor review needed.

    Args:
        task_id: Task ID needing review
        reason: Reason for escalation
    """
    try:
        task = task_store.get_task(task_id)
        project_id = str(task.get("project_id")) if task and task.get("project_id") else None
        if not project_id:
            raise ValueError(f"Task {task_id} missing project_id")
        create_notification(
            project_id=project_id,
            notification_type="task_needs_input",
            title=f"Supervisor Review Required: {task_id}",
            message=reason,
            severity="warning",
            metadata={"task_id": task_id, "escalation_reason": reason},
        )
        logger.info("supervisor_review_notification_sent", task_id=task_id)
    except Exception as e:
        logger.warning("notification_failed", task_id=task_id, error=str(e))


def _get_project_path(task: dict[str, Any]) -> Path:
    """Get project path from task.

    Args:
        task: Task dict

    Returns:
        Path to project root
    """
    project_id = task.get("project_id")
    if not project_id:
        raise ValueError("Task missing project_id")

    from app.storage.projects import get_project_root_path

    root = get_project_root_path(project_id)
    if not root:
        raise ValueError(f"Project {project_id} not found or has no root_path")
    return Path(root)


def _auto_merge_pr(task_id: str, pr_url: str, project_path: Path) -> bool:
    """Auto-merge approved PR via gh CLI.

    Uses `gh pr merge --squash --delete-branch` to merge the PR.

    Args:
        task_id: Task ID for logging
        pr_url: PR URL to merge
        project_path: Path to run command in

    Returns:
        True if merge succeeded, False otherwise (non-blocking)
    """
    try:
        # Extract PR number from URL
        # Format: https://github.com/owner/repo/pull/123
        pr_number = pr_url.split("/pull/")[-1].strip("/")

        result = subprocess.run(
            [
                "gh",
                "pr",
                "merge",
                pr_number,
                "--squash",
                "--delete-branch",
                "--admin",  # Use admin merge to bypass branch protection
            ],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            logger.info("pr_auto_merged", task_id=task_id, pr_url=pr_url)
            log_task_event(task_id, f"PR merged: {pr_url}")
            return True
        error = result.stderr.strip() or "Unknown error"
        logger.warning("pr_auto_merge_failed", task_id=task_id, pr_url=pr_url, error=error)
        log_task_event(task_id, f"Auto-merge failed: {error}")
        return False

    except subprocess.TimeoutExpired:
        logger.warning("pr_auto_merge_timeout", task_id=task_id, pr_url=pr_url)
        return False
    except Exception as e:
        logger.warning("pr_auto_merge_error", task_id=task_id, error=str(e))
        return False
