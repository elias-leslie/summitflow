"""Background tasks for generating tasks from Explorer scans."""

from __future__ import annotations

import logging
from typing import Any

from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.projects import get_project_root_path
from app.storage.tasks import delete_task
from app.storage.tasks.queries import list_tasks
from app.tasks.autonomous.step_builders import build_refactor_steps, calculate_target_lines
from app.tasks.autonomous.task_builders import (
    create_refactor_task,
    create_schema_task,
)
from app.tasks.autonomous.violation_handlers import (
    get_violation_done_when,
    get_violation_objective,
    get_violation_steps,
    get_violation_title,
)

logger = logging.getLogger(__name__)


def _delete_existing_refactor_tasks(project_id: str) -> int:
    """Delete existing refactor tasks for a project, preserving in-progress work.

    Skips tasks that are running, paused, or blocked — these represent
    active work that should not be destroyed by a regenerate cycle.
    """
    protected_statuses = {"running", "paused", "blocked"}
    refactor_tasks = list_tasks(project_id=project_id, task_type_filter="refactor", limit=500)
    deleted = 0
    protected = 0
    for task in refactor_tasks:
        task_id = task.get("id")
        if not task_id:
            continue
        if task.get("status") in protected_statuses:
            protected += 1
            logger.info(f"Protecting in-progress task {task_id}: {task.get('title', '')[:50]}")
            continue
        try:
            if delete_task(task_id):
                deleted += 1
                logger.info(f"Deleted refactor task {task_id}: {task.get('title', '')[:50]}")
        except Exception as e:
            logger.warning(f"Failed to delete task {task_id}: {e}")
    if deleted > 0 or protected > 0:
        logger.info(
            f"Refactor task cleanup for {project_id}: "
            f"deleted={deleted}, protected={protected}"
        )
    return deleted


def _process_refactor_target(
    project_id: str,
    target: dict[str, Any],
    project_root: str | None = None,
    skip_existing: bool = True,
) -> bool:
    """Process a single refactor target and create task if needed."""
    relative_path = target.get("path", "")
    priority = target.get("priority", "medium")
    reason = target.get("reason", "High complexity")
    complexity = target.get("complexity_score", 0)
    lines = target.get("lines_of_code", 0)

    if skip_existing and task_store.task_exists_for_file(project_id, relative_path):
        logger.info("Skipping %s: task already exists", relative_path)
        return False

    target_lines = calculate_target_lines(lines)

    if lines <= target_lines:
        logger.info(
            "Skipping %s: %d lines already at/below target %d", relative_path, lines, target_lines
        )
        return False
    if lines > 0 and (lines - target_lines) / lines < 0.20:
        reduction_pct = (lines - target_lines) / lines * 100
        logger.info(
            "Skipping %s: reduction %.0f%% below 20%% threshold", relative_path, reduction_pct
        )
        return False
    tier = 3 if (complexity > 15 or lines > 500) else (2 if (complexity > 10 or lines > 300) else 1)
    file_path = f"{project_root}/{relative_path}" if project_root else relative_path
    is_frontend = relative_path.startswith("frontend/")
    steps = build_refactor_steps(relative_path, file_path, lines, target_lines, is_frontend)

    task_id, issue_id = create_refactor_task(
        project_id=project_id,
        relative_path=relative_path,
        file_path=file_path,
        reason=reason,
        complexity=complexity,
        lines=lines,
        target_lines=target_lines,
        priority=priority,
        tier=tier,
        steps=steps,
    )

    if task_id:
        logger.info(
            f"Created task {task_id} with spirit+criteria, linked to issue {issue_id}: {reason}"
        )
        return True
    return False


def generate_tasks_from_scan(project_id: str) -> dict[str, Any]:
    """Generate refactoring tasks from Explorer scan results (skips existing)."""
    try:
        result = get_refactor_targets(project_id, limit=20)
        targets = result.get("targets", [])
        created = 0
        scanned = 0
        skipped = 0

        for target in targets:
            scanned += 1
            if _process_refactor_target(project_id, target, skip_existing=True):
                created += 1
            else:
                skipped += 1

        logger.info(
            f"Task generation complete for {project_id}: "
            f"created={created}, scanned={scanned}, skipped={skipped}"
        )
        return {"created_count": created, "scanned_count": scanned, "skipped_count": skipped}
    except Exception as e:
        logger.error(f"Error generating tasks from scan: {e}")
        return {"error": str(e), "created_count": 0, "scanned_count": 0, "skipped_count": 0}


def regenerate_refactor_tasks_sync(project_id: str) -> dict[str, Any]:
    """Delete all existing refactor tasks and regenerate from current scan (sync)."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        logger.error(f"Project {project_id} not found or has no root_path")
        return {
            "error": f"Project {project_id} not found",
            "deleted_count": 0,
            "created_count": 0,
            "scanned_count": 0,
        }

    deleted_count = _delete_existing_refactor_tasks(project_id)
    result = get_refactor_targets(project_id, limit=20)
    targets = result.get("targets", [])
    created = 0
    scanned = 0
    skipped = 0

    for target in targets:
        scanned += 1
        if _process_refactor_target(
            project_id, target, project_root=project_root, skip_existing=False
        ):
            created += 1
        else:
            skipped += 1

    logger.info(
        f"Refactor task regeneration complete for {project_id}: "
        f"deleted={deleted_count}, created={created}, scanned={scanned}, skipped={skipped}"
    )
    return {
        "deleted_count": deleted_count,
        "created_count": created,
        "scanned_count": scanned,
        "skipped_count": skipped,
    }


def regenerate_refactor_tasks(project_id: str) -> dict[str, Any]:
    """Delete all existing refactor tasks and regenerate from current scan."""
    try:
        return regenerate_refactor_tasks_sync(project_id)
    except Exception as e:
        logger.error(f"Error regenerating refactor tasks: {e}")
        return {"error": str(e), "deleted_count": 0, "created_count": 0, "scanned_count": 0}


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
