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


def _cancel_stale_task(task: dict[str, Any], max_age_days: int) -> bool:
    """Cancel a single stale task. Returns True if cancelled, False if skipped."""
    task_id = task.get("id")
    if not task_id:
        return False

    try:
        task_store.update_task(task_id, status="cancelled")
        log_task_event(
            task_id,
            f"Auto-cancelled: No activity for {max_age_days}+ days. "
            "Stale auto-generated task archived.",
        )
        logger.info(f"Cancelled stale task {task_id}: {task.get('title', '')[:50]}")
        return True
    except Exception:
        logger.exception("Failed to cancel task %s", task_id)
        return False


def cleanup_stale_tasks(max_age_days: int = 30) -> dict[str, Any]:
    """Archive auto-generated tasks that have been pending without activity."""
    from app.storage.tasks import get_stale_tasks

    try:
        stale_tasks = get_stale_tasks(max_age_days=max_age_days, limit=100)
        cancelled = sum(
            1 for task in stale_tasks if _cancel_stale_task(task, max_age_days)
        )
        skipped = len(stale_tasks) - cancelled

        logger.info(f"Stale task cleanup complete: cancelled={cancelled}, skipped={skipped}")
        return {
            "cancelled_count": cancelled,
            "skipped_count": skipped,
            "max_age_days": max_age_days,
        }
    except Exception as e:
        logger.error(f"Error in stale task cleanup: {e}")
        return {"error": str(e), "cancelled_count": 0, "skipped_count": 0}


def _create_schema_task_for_violation(
    project_id: str,
    table_name: str,
    violation: dict[str, Any],
    column_count: int,
) -> bool:
    """Create a schema task for a single violation. Returns True if created."""
    violation_type = violation.get("type", "")
    detail = violation.get("detail", "")
    severity = violation.get("severity", "warning")
    file_path = f"table:{table_name}"

    if task_store.task_exists_for_file(project_id, file_path):
        return False

    tier = 2 if violation_type == "god_table" else 1
    try:
        task_id, _ = create_schema_task(
            project_id=project_id,
            table_name=table_name,
            violation_type=violation_type,
            detail=detail,
            severity=severity,
            metadata={"column_count": column_count},
            steps=get_violation_steps(violation_type, table_name, detail),
            title=get_violation_title(violation_type, table_name),
            objective=get_violation_objective(violation_type, table_name, detail),
            done_when=get_violation_done_when(violation_type, table_name),
            tier=tier,
        )
    except Exception:
        logger.exception(
            "Failed to create schema task for project_id=%s table_name=%s violation_type=%s",
            project_id,
            table_name,
            violation_type,
        )
        return False
    return bool(task_id)


def _process_table_violations(
    project_id: str,
    table: dict[str, Any],
) -> tuple[int, int]:
    """Process all violations for a single table. Returns (created, skipped)."""
    metadata = table.get("metadata", {})
    violations = metadata.get("violations", [])
    if not violations:
        return 0, 0

    table_name = table.get("path", "")
    column_count = metadata.get("column_count", 0)
    created = 0
    skipped = 0

    for violation in violations:
        if _create_schema_task_for_violation(project_id, table_name, violation, column_count):
            created += 1
        else:
            skipped += 1

    return created, skipped


def generate_schema_tasks(project_id: str) -> dict[str, Any]:
    """Generate schema tasks from database table violations."""
    from app.storage import explorer_entries

    try:
        tables = explorer_entries.get_entries(project_id, {"type": "table"})
        created = 0
        scanned = 0
        skipped = 0

        for table in tables:
            table_created, table_skipped = _process_table_violations(project_id, table)
            if table.get("metadata", {}).get("violations"):
                scanned += 1
            created += table_created
            skipped += table_skipped

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
