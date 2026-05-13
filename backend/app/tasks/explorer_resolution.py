"""Explorer issue resolution checking and auto-close logic."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..services import explorer
from ..services.task_issue_mapper import QAIssue, close_task_for_issue
from ..storage import qa_issues as qa_storage

logger = get_logger(__name__)

# Issue type constants
ISSUE_TYPE_ERROR = "error"
ISSUE_TYPE_COMPLEXITY = "complexity"
ISSUE_TYPE_STALE_FILE = "stale_file"
ISSUE_TYPE_BLOAT = "bloat"

# Stale status values that indicate an active stale issue
STALE_ACTIVE_STATUSES = ("stale", "orphan")

# Bloat level values that indicate an active bloat issue
BLOAT_ACTIVE_LEVELS = ("warning", "critical")

# Complexity threshold above which a file is considered complex (tier 1)
COMPLEXITY_THRESHOLD = 10

# Resolution reason logged when a scan no longer detects the issue
RESOLUTION_REASON_NOT_DETECTED = "Issue no longer detected in scan"

# Metadata keys used in explorer entries and issue metadata
META_COMPLEXITY_SCORE = "complexity_score"
META_STALE_STATUS = "stale_status"
META_BLOAT_LEVEL = "bloat_level"


def _mark_and_close_issue(
    issue: dict[str, Any],
    scan_id: int | None,
) -> bool:
    """Mark an issue as resolved and close its linked task.

    Args:
        issue: Issue dict from qa_issues table
        scan_id: Optional scan ID for tracking

    Returns:
        True if the linked task was successfully closed
    """
    qa_storage.mark_issue_resolved(
        issue["id"],
        scan_id=scan_id,
        reason=RESOLUTION_REASON_NOT_DETECTED,
    )

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
    return close_task_for_issue(qa_issue)


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
        if not issue_still_exists(project_id, issue) and _mark_and_close_issue(issue, scan_id):
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


def _complexity_issue_still_exists(
    entry: dict[str, Any],
    issue_metadata: dict[str, Any],
) -> bool:
    """Check if a complexity issue still exists for a file entry.

    Args:
        entry: Explorer entry dict for the file
        issue_metadata: Parsed metadata from the issue

    Returns:
        True if the complexity issue persists
    """
    entry_metadata = entry.get("metadata", {})
    complexity = entry_metadata.get(META_COMPLEXITY_SCORE, 0)

    # target_lines is generation context, not a hard acceptance gate.
    return bool(complexity >= COMPLEXITY_THRESHOLD)


def _stale_file_issue_still_exists(entry: dict[str, Any]) -> bool:
    """Check if a stale_file issue still exists for a file entry.

    Args:
        entry: Explorer entry dict for the file

    Returns:
        True if the file is still stale or orphaned
    """
    metadata = entry.get("metadata", {})
    stale_status = metadata.get(META_STALE_STATUS)
    return bool(stale_status in STALE_ACTIVE_STATUSES)


def _bloat_issue_still_exists(entry: dict[str, Any]) -> bool:
    """Check if a bloat issue still exists for a file entry.

    Args:
        entry: Explorer entry dict for the file

    Returns:
        True if the file still has a warning or critical bloat level
    """
    metadata = entry.get("metadata", {})
    bloat_level = metadata.get(META_BLOAT_LEVEL)
    return bool(bloat_level in BLOAT_ACTIVE_LEVELS)


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
    if issue_type == ISSUE_TYPE_ERROR:
        return _error_issue_still_exists(project_id, issue, issue_metadata)

    if not file_path:
        # Non-file issues without special handling - assume still exists
        return True

    # Get the explorer entry for this file
    entry = explorer.get_entry(project_id, "file", file_path)
    if not entry:
        # File was deleted - issue is resolved
        return False

    # Dispatch to issue type-specific check
    if issue_type == ISSUE_TYPE_COMPLEXITY:
        return _complexity_issue_still_exists(entry, issue_metadata)
    elif issue_type == ISSUE_TYPE_STALE_FILE:
        return _stale_file_issue_still_exists(entry)
    elif issue_type == ISSUE_TYPE_BLOAT:
        return _bloat_issue_still_exists(entry)

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
