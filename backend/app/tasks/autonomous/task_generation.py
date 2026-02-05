"""Celery tasks for generating tasks from Explorer scans."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.celery_app import celery_app
from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.projects import get_project_root_path
from app.storage.tasks import delete_task
from app.storage.tasks.queries import list_tasks
from app.tasks.autonomous.step_builders import build_refactor_steps, calculate_target_lines
from app.tasks.autonomous.task_builders import (
    create_architecture_task,
    create_refactor_task,
    create_schema_task,
)
from app.tasks.autonomous.violation_handlers import (
    get_consolidated_architecture_done_when,
    get_consolidated_architecture_objective,
    get_consolidated_architecture_title,
    get_violation_done_when,
    get_violation_objective,
    get_violation_steps,
    get_violation_title,
)

logger = logging.getLogger(__name__)


def _delete_existing_refactor_tasks(project_id: str) -> int:
    """Delete all existing refactor tasks for a project."""
    refactor_tasks = list_tasks(project_id=project_id, task_type_filter="refactor", limit=500)
    deleted = 0
    for task in refactor_tasks:
        task_id = task.get("id")
        if task_id:
            try:
                if delete_task(task_id):
                    deleted += 1
                    logger.info(f"Deleted refactor task {task_id}: {task.get('title', '')[:50]}")
            except Exception as e:
                logger.warning(f"Failed to delete task {task_id}: {e}")
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} existing refactor tasks for {project_id}")
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
        return False

    target_lines = calculate_target_lines(lines)
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


@celery_app.task(
    name="summitflow.generate_tasks_from_scan",
    acks_late=True,
    time_limit=600,  # 10 minutes hard limit
    soft_time_limit=540,  # 9 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,  # Max 2 minutes between retries
    max_retries=3,
)
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


@celery_app.task(
    name="summitflow.regenerate_refactor_tasks",
    acks_late=True,
    time_limit=900,  # 15 minutes hard limit
    soft_time_limit=840,  # 14 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=180,  # Max 3 minutes between retries
    max_retries=3,
)
def regenerate_refactor_tasks(project_id: str) -> dict[str, Any]:
    """Delete all existing refactor tasks and regenerate from current scan."""
    try:
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

        for target in targets:
            scanned += 1
            if _process_refactor_target(
                project_id, target, project_root=project_root, skip_existing=False
            ):
                created += 1

        logger.info(
            f"Refactor task regeneration complete for {project_id}: "
            f"deleted={deleted_count}, created={created}, scanned={scanned}"
        )
        return {"deleted_count": deleted_count, "created_count": created, "scanned_count": scanned}
    except Exception as e:
        logger.error(f"Error regenerating refactor tasks: {e}")
        return {"error": str(e), "deleted_count": 0, "created_count": 0, "scanned_count": 0}


@celery_app.task(
    name="summitflow.generate_schema_tasks",
    acks_late=True,
    time_limit=600,  # 10 minutes hard limit
    soft_time_limit=540,  # 9 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,  # Max 2 minutes between retries
    max_retries=3,
)
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


@celery_app.task(
    name="summitflow.cleanup_stale_tasks",
    acks_late=True,
    time_limit=600,  # 10 minutes hard limit
    soft_time_limit=540,  # 9 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,  # Max 2 minutes between retries
    max_retries=3,
)
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


@celery_app.task(
    name="summitflow.generate_architecture_tasks",
    acks_late=True,
    time_limit=600,  # 10 minutes hard limit
    soft_time_limit=540,  # 9 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,  # Max 2 minutes between retries
    max_retries=3,
)
def generate_architecture_tasks(project_id: str) -> dict[str, Any]:
    """Generate tasks from architecture violations detected by Explorer."""
    from app.storage import explorer_entries

    try:
        entries = explorer_entries.get_entries(project_id, {"type": "architecture"})
        violations_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for entry in entries:
            metadata = entry.get("metadata", {})
            violations = metadata.get("violations", [])
            module_path = entry.get("path", "")
            for violation in violations:
                violation_type = violation.get("violation_type", "")
                violations_by_type[violation_type].append({**violation, "module_path": module_path})

        if not violations_by_type:
            logger.info(f"No architecture violations found for {project_id}")
            return {"created_count": 0, "scanned_count": 0, "skipped_count": 0}

        created = 0
        skipped = 0
        scanned = len(violations_by_type)

        for violation_type, violations in violations_by_type.items():
            issue_path = f"architecture:{violation_type}"
            if task_store.task_exists_for_file(project_id, issue_path):
                skipped += 1
                logger.info(f"Skipping {violation_type}: task already exists")
                continue

            affected_files = list(
                {v.get("file_path", "") for v in violations if v.get("file_path")}
            )
            severity = "error" if violation_type == "parallel_implementation" else "warning"
            tier = 2 if violation_type == "parallel_implementation" else 1
            complexity = "STANDARD" if len(affected_files) > 5 else "SIMPLE"
            auto_approve = tier == 1 and len(affected_files) <= 5

            task_id, _ = create_architecture_task(
                project_id=project_id,
                violation_type=violation_type,
                violations=violations,
                affected_files=affected_files,
                title=get_consolidated_architecture_title(violation_type, len(affected_files)),
                severity=severity,
                tier=tier,
                objective=get_consolidated_architecture_objective(violation_type, affected_files),
                done_when=get_consolidated_architecture_done_when(violation_type),
                complexity=complexity,
                auto_approve=auto_approve,
            )
            if task_id:
                created += 1

        logger.info(
            f"Architecture task generation complete for {project_id}: "
            f"created={created}, scanned={scanned}, skipped={skipped}"
        )
        return {"created_count": created, "scanned_count": scanned, "skipped_count": skipped}
    except Exception as e:
        logger.error(f"Error generating architecture tasks: {e}")
        return {"error": str(e), "created_count": 0, "scanned_count": 0, "skipped_count": 0}
