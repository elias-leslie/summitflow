"""Explorer issue resolution checking and auto-close logic."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..services import explorer
from ..services.task_issue_mapper import QAIssue, close_task_for_issue
from ..storage import qa_issues as qa_storage

logger = get_logger(__name__)


def check_and_close_resolved_issues(project_id: str, scan_id: int | None = None) -> int:
    """Check for resolved issues and auto-close linked tasks.

    After a scan, check which open issues are no longer detected.
    For issues linked to SummitFlow tasks, auto-close the tasks.

    This implements the self-healing loop:
    1. Scan detects issue -> create task
    2. User/agent fixes issue
    3. Next scan doesn't detect issue -> mark resolved, close task

    Args:
        project_id: Project that was scanned
        scan_id: Optional scan ID for tracking

    Returns:
        Number of tasks auto-closed
    """
    closed_count = 0

    # Get all open issues linked to tasks
    linked_issues = qa_storage.get_issues_linked_to_tasks(project_id)
    if not linked_issues:
        return 0

    logger.info(
        "checking_resolved_issues",
        project_id=project_id,
        linked_count=len(linked_issues),
    )

    # Check each linked issue to see if it's still valid
    for issue in linked_issues:
        if not issue_still_exists(project_id, issue):
            # Issue is resolved - mark it and close the task
            qa_storage.mark_issue_resolved(
                issue["id"],
                scan_id=scan_id,
                reason="Issue no longer detected in scan",
            )

            # Close the linked task
            qa_issue = QAIssue(
                id=issue["id"],
                project_id=issue["project_id"],
                issue_type=issue["issue_type"],
                severity=issue["severity"],
                title=issue["title"],
                description=issue.get("description"),
                file_path=issue.get("file_path"),
                st_task_id=issue["st_task_id"],
            )
            if close_task_for_issue(qa_issue):
                closed_count += 1
                logger.info(
                    "auto_closed_task",
                    issue_id=issue["id"],
                    task_id=issue["st_task_id"],
                )

    if closed_count > 0:
        logger.info(
            "self_healing_complete",
            project_id=project_id,
            tasks_closed=closed_count,
        )

    return closed_count


def issue_still_exists(project_id: str, issue: dict[str, Any]) -> bool:
    """Check if a QA issue still exists in the codebase.

    For file-based issues (complexity, stale_file), check if the
    file still has the issue in the explorer entries.

    For error issues, check if the error observation still exists
    and hasn't been marked as resolved.

    Args:
        project_id: Project ID
        issue: Issue dict from qa_issues table

    Returns:
        True if issue still exists, False if resolved
    """
    file_path = issue.get("file_path")
    issue_type = issue.get("issue_type")
    issue_metadata = issue.get("metadata") or {}

    # Handle error issues separately (may not have file_path)
    if issue_type == "error":
        return _error_issue_still_exists(project_id, issue, issue_metadata)

    if not file_path:
        # Non-file issues without special handling - assume still exists
        return True

    # Get the explorer entry for this file
    entry = explorer.get_entry(project_id, "file", file_path)
    if not entry:
        # File was deleted - issue is resolved
        return False

    # Check issue type-specific criteria
    if issue_type == "complexity":
        # Check if complexity is still above threshold OR line count still above target
        entry_metadata = entry.get("metadata", {})
        complexity = entry_metadata.get("complexity_score", 0)
        lines = entry_metadata.get("lines_of_code", 0)

        # If issue has a target_lines in metadata, use that for line count check
        target_lines = issue_metadata.get("target_lines")
        if target_lines and lines >= target_lines:
            # File still above target line count - issue persists
            return True

        # Fall back to complexity check (threshold matches task generation: tier 1 starts at complexity > 10)
        return bool(complexity >= 10)

    elif issue_type == "stale_file":
        # Check if file is still stale (no commits in 180+ days)
        metadata = entry.get("metadata", {})
        stale_status = metadata.get("stale_status")
        return bool(stale_status in ("stale", "orphan"))

    elif issue_type == "bloat":
        # Check if file is still bloated
        metadata = entry.get("metadata", {})
        bloat_level = metadata.get("bloat_level")
        return bool(bloat_level in ("warning", "critical"))

    # Default: assume issue still exists
    return True


def _error_issue_still_exists(
    project_id: str,
    issue: dict[str, Any],
    issue_metadata: dict[str, Any],
) -> bool:
    """Check if an error issue still exists.

    Memory system removed - this function now returns True (issue still exists)
    as a safe default. Error resolution tracking moved to quality gate system.

    Args:
        project_id: Project ID
        issue: Issue dict from qa_issues table
        issue_metadata: Parsed metadata from issue

    Returns:
        True if error still exists (safe default without memory system)
    """
    # Memory system removed - return True as safe default
    # Error tracking now handled by quality gate system (quality_check_results table)
    return True
