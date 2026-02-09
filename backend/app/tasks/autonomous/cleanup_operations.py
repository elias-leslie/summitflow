"""Cleanup and schema task generation operations."""

from __future__ import annotations

import logging
from typing import Any

from app.storage import log_task_event
from app.storage import tasks as task_store
from app.tasks.autonomous.task_builders import create_schema_task
from app.tasks.autonomous.violation_handlers import (
    get_violation_done_when,
    get_violation_objective,
    get_violation_steps,
    get_violation_title,
)

logger = logging.getLogger(__name__)


def cleanup_stale_tasks(max_age_days: int = 30) -> dict[str, Any]:
    """Archive auto-generated tasks that have been pending without activity."""
    from app.storage.tasks import get_stale_tasks

    try:
        stale_tasks = get_stale_tasks(max_age_days=max_age_days, limit=100)
        cancelled = 0
        skipped = 0

        for task in stale_tasks:
            task_id = task.get("id")
            if not task_id:
                skipped += 1
                continue

            try:
                task_store.update_task(task_id, status="cancelled")
                log_task_event(
                    task_id,
                    f"Auto-cancelled: No activity for {max_age_days}+ days. "
                    "Stale auto-generated task archived.",
                )
                cancelled += 1
                logger.info(f"Cancelled stale task {task_id}: {task.get('title', '')[:50]}")
            except Exception as task_err:
                logger.error(f"Failed to cancel task {task_id}: {task_err}")
                skipped += 1

        logger.info(f"Stale task cleanup complete: cancelled={cancelled}, skipped={skipped}")
        return {
            "cancelled_count": cancelled,
            "skipped_count": skipped,
            "max_age_days": max_age_days,
        }
    except Exception as e:
        logger.error(f"Error in stale task cleanup: {e}")
        return {"error": str(e), "cancelled_count": 0, "skipped_count": 0}


def generate_schema_tasks(project_id: str) -> dict[str, Any]:
    """Generate schema tasks from database table violations."""
    from app.storage import explorer_entries

    try:
        tables = explorer_entries.get_entries(project_id, {"type": "table"})
        created = 0
        scanned = 0
        skipped = 0

        for table in tables:
            metadata = table.get("metadata", {})
            violations = metadata.get("violations", [])
            if not violations:
                continue

            scanned += 1
            table_name = table.get("path", "")

            for violation in violations:
                violation_type = violation.get("type", "")
                detail = violation.get("detail", "")
                severity = violation.get("severity", "warning")
                file_path = f"table:{table_name}"

                if task_store.task_exists_for_file(project_id, file_path):
                    skipped += 1
                    continue

                tier = 2 if violation_type == "god_table" else 1
                task_id, _ = create_schema_task(
                    project_id=project_id,
                    table_name=table_name,
                    violation_type=violation_type,
                    detail=detail,
                    severity=severity,
                    metadata={"column_count": metadata.get("column_count", 0)},
                    steps=get_violation_steps(violation_type, table_name, detail),
                    title=get_violation_title(violation_type, table_name),
                    objective=get_violation_objective(violation_type, table_name, detail),
                    done_when=get_violation_done_when(violation_type, table_name),
                    tier=tier,
                )
                if task_id:
                    created += 1

        logger.info(
            f"Schema task generation complete for {project_id}: "
            f"created={created}, scanned={scanned}, skipped={skipped}"
        )
        return {"created_count": created, "scanned_count": scanned, "skipped_count": skipped}
    except Exception as e:
        logger.error(f"Error generating schema tasks: {e}")
        return {"error": str(e), "created_count": 0, "scanned_count": 0, "skipped_count": 0}


def generate_architecture_tasks(project_id: str) -> dict[str, Any]:
    """Architecture task generation — disabled.

    Architecture violations are still detected by Explorer scans and stored
    in explorer_entries (visible on the Explorer health dashboard). Task
    generation is disabled because auto-generated architecture tasks lack
    actionable subtasks/steps and created unexecutable noise.

    Users can manually create tasks when they want to act on violations.
    """
    logger.info(
        f"Architecture task generation disabled for {project_id}. "
        "Violations are still tracked in Explorer health dashboard."
    )
    return {"created_count": 0, "scanned_count": 0, "skipped_count": 0}
