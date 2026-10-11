"""Self-healing bug-task creation from systemd journal errors."""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ...storage.tasks.core import create_task
from ...storage.tasks.dedup import bug_task_exists_for_error
from ..journal_monitor import (
    ERROR_PRIORITY_THRESHOLD,
    PRIORITY_ALERT,
    PRIORITY_CRIT,
    PRIORITY_DEBUG,
    PRIORITY_EMERG,
    PRIORITY_ERR,
    PRIORITY_INFO,
    PRIORITY_WARNING,
    JournalError,
    SystemdMonitor,
    compute_error_hash,
)

logger = get_logger(__name__)

_MESSAGE_PREVIEW_LEN = 80
_PRIORITY_NAMES = {PRIORITY_EMERG: "EMERGENCY", PRIORITY_ALERT: "ALERT", PRIORITY_CRIT: "CRITICAL", PRIORITY_ERR: "ERROR"}

__all__ = [
    "ERROR_PRIORITY_THRESHOLD",
    "PRIORITY_DEBUG",
    "PRIORITY_INFO",
    "PRIORITY_WARNING",
    "JournalError",
    "SystemdMonitor",
    "compute_error_hash",
    "create_error_task",
    "process_journal_errors",
]


def _build_task_description(error: JournalError) -> str:
    """Build the markdown description body for a bug task."""
    priority_name = _PRIORITY_NAMES.get(error.priority, "ERROR")
    return (
        f"**Detected:** {error.timestamp.isoformat()}\n"
        f"**Service:** {error.unit}\n"
        f"**Priority:** {priority_name}\n\n"
        f"**Error Message:**\n```\n{error.message}\n```\n\n"
        f"**Error Hash:** {error.error_hash}\n\n"
        "This bug was auto-created from systemd journal monitoring.\n"
        "The error was detected at runtime and requires investigation."
    )


def create_error_task(
    project_id: str,
    error: JournalError,
    skip_dedup: bool = False,
) -> dict[str, Any] | None:
    """Create a bug task from a journal error; returns None if duplicate exists."""
    preview = error.message[:_MESSAGE_PREVIEW_LEN]
    if len(error.message) > _MESSAGE_PREVIEW_LEN:
        preview += "..."
    title = f"Fix: {preview}"

    if not skip_dedup and bug_task_exists_for_error(project_id, title):
        logger.info("skipping_duplicate_error_task", error_hash=error.error_hash, title=title[:50])
        return None

    task = create_task(
        project_id=project_id, title=title, description=_build_task_description(error),
        priority=2, task_type="bug", complexity="STANDARD", execution_mode="autonomous",
    )
    logger.info("created_error_task", task_id=task["id"], error_hash=error.error_hash, unit=error.unit)
    return task


def process_journal_errors(
    project_id: str,
    monitor: SystemdMonitor | None = None,
) -> dict[str, int]:
    """Process journal errors and create bug tasks; returns created/skipped/errors counts."""
    if monitor is None:
        monitor = SystemdMonitor()
    results: dict[str, int] = {"created": 0, "skipped": 0, "errors": 0}
    try:
        for error in monitor.get_new_errors():
            try:
                task = create_error_task(project_id, error)
                results["created" if task else "skipped"] += 1
            except Exception as e:
                logger.error("task_creation_failed", error_hash=error.error_hash, error=str(e))
                results["errors"] += 1
    except Exception as e:
        logger.error("process_journal_errors_failed", error=str(e))
        results["errors"] += 1
    if results["created"] > 0:
        logger.info("journal_processing_complete", **results)
    return results
