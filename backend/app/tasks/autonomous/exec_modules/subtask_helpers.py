"""Helper functions for subtask execution."""

from __future__ import annotations

import traceback
from typing import Any

from ....core.debug import debug, debug_error, debug_section
from ....logging_config import get_logger
from .events import emit_error, emit_log, emit_progress
from .steps import compute_issue_id

logger = get_logger(__name__)


def initialize_subtask_logging(
    task_id: str, subtask_short_id: str, subtask_desc: str, project_id: str
) -> None:
    """Initialize logging for subtask execution."""
    debug_section(f"Subtask {subtask_short_id}", task_id=task_id, project_id=project_id)
    debug(
        "Starting subtask execution",
        task_id=task_id,
        project_id=project_id,
        subtask_id=subtask_short_id,
        description=subtask_desc,
    )
    logger.info("Executing subtask", task_id=task_id, subtask_id=subtask_short_id)
    emit_log(task_id, "info", f"Starting subtask {subtask_short_id}: {subtask_desc}", project_id=project_id)
    emit_progress(task_id, subtask_id=subtask_short_id, status="in_progress", project_id=project_id)


def handle_execution_error(
    task_id: str,
    subtask_short_id: str,
    project_id: str,
    error: Exception,
    issue_counts: dict[str, int],
) -> dict[str, Any]:
    """Handle execution error and return failure result."""
    error_str = str(error)
    logger.warning(
        "Subtask execution failed",
        subtask_id=subtask_short_id,
        error=error_str,
        traceback=traceback.format_exc(),
    )
    issue_id = compute_issue_id(error_str)
    issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
    emit_error(task_id, f"Subtask {subtask_short_id} error: {error_str}", project_id=project_id)
    debug_error(
        f"Subtask {subtask_short_id} exception",
        task_id=task_id,
        project_id=project_id,
        error=error_str,
        issue_id=issue_id,
    )
    return {
        "subtask_id": subtask_short_id,
        "status": "failed",
        "error": error_str,
        "issue_id": issue_id,
        "issue_count": issue_counts[issue_id],
    }
