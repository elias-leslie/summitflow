"""Background tasks for generating tasks from Explorer scans.

This module serves as the main entry point for task generation operations,
delegating to specialized modules for different task types.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tasks.autonomous.cleanup_operations import (
    cleanup_stale_tasks,
    generate_architecture_tasks,
    generate_schema_tasks,
)
from app.tasks.autonomous.refactor_generation import (
    generate_refactor_tasks_internal,
    regenerate_refactor_tasks_impl,
)

logger = logging.getLogger(__name__)

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
    """Generate refactoring tasks from Explorer scan results (skips existing)."""
    try:
        result = generate_refactor_tasks_internal(project_id, skip_existing=True)
        logger.info(
            f"Task generation complete for {project_id}: "
            f"created={result['created_count']}, scanned={result['scanned_count']}, "
            f"skipped={result['skipped_count']}"
        )
        return result
    except Exception as e:
        logger.error(f"Error generating tasks from scan: {e}")
        return {"error": str(e), "created_count": 0, "scanned_count": 0, "skipped_count": 0}


def regenerate_refactor_tasks_sync(project_id: str) -> dict[str, Any]:
    """Synchronize refactor tasks with the latest scan results (sync)."""
    return regenerate_refactor_tasks_impl(project_id)


def regenerate_refactor_tasks(project_id: str) -> dict[str, Any]:
    """Synchronize refactor tasks with the latest scan results."""
    try:
        return regenerate_refactor_tasks_sync(project_id)
    except Exception as e:
        logger.error(f"Error regenerating refactor tasks: {e}")
        return {"error": str(e), "deleted_count": 0, "created_count": 0, "scanned_count": 0}
