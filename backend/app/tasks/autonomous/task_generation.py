"""Background tasks for generating tasks from Explorer scans.

This module serves as the main entry point for task generation operations,
delegating to specialized modules for different task types.
"""

from __future__ import annotations

from typing import Any

from app.tasks.autonomous.cleanup_operations import (
    cleanup_stale_tasks,
    generate_architecture_tasks,
    generate_schema_tasks,
)
from app.tasks.autonomous.refactor_generation import (
    regenerate_refactor_tasks_impl,
)

from ...logging_config import get_logger

logger = get_logger(__name__)

# Re-export cleanup and schema operations for backward compatibility
__all__ = [
    "cleanup_stale_tasks",
    "generate_architecture_tasks",
    "generate_schema_tasks",
    "generate_tasks_from_scan",
    "regenerate_refactor_tasks",
    "regenerate_refactor_tasks_sync",
]


def generate_tasks_from_scan(project_id: str) -> dict[str, Any]:
    """Synchronize refactor tasks from the latest Explorer scan.

    Scheduled automation and manual sync should follow the same path so we do
    not drift between "background" and "operator-triggered" queue quality.
    """
    try:
        result = regenerate_refactor_tasks_impl(project_id)
        logger.info(
            "Task generation complete for %s: closed=%d, created=%d, scanned=%d, skipped=%d",
            project_id, result['closed_count'], result['created_count'],
            result['scanned_count'], result['skipped_count'],
        )
        return result
    except Exception as e:
        logger.error("Error generating tasks from scan: %s", e)
        return {
            "error": str(e),
            "closed_count": 0,
            "created_count": 0,
            "scanned_count": 0,
            "skipped_count": 0,
        }


def regenerate_refactor_tasks_sync(project_id: str) -> dict[str, Any]:
    """Synchronize refactor tasks with the latest scan results (sync)."""
    return regenerate_refactor_tasks_impl(project_id)


def regenerate_refactor_tasks(project_id: str) -> dict[str, Any]:
    """Synchronize refactor tasks with the latest scan results."""
    try:
        return regenerate_refactor_tasks_sync(project_id)
    except Exception as e:
        logger.error("Error regenerating refactor tasks: %s", e)
        return {"error": str(e), "deleted_count": 0, "created_count": 0, "scanned_count": 0}
