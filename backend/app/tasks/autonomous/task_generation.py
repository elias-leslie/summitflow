"""Celery tasks for generating tasks from scans and observations."""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.services.task_issue_mapper import link_issue_to_task
from app.storage import qa_issues as qa_storage
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.steps import bulk_create_steps
from app.storage.subtasks import bulk_create_subtasks
from app.storage.task_spirit import approve_plan, create_task_spirit
from app.storage.verification import create_task_criterion

logger = logging.getLogger(__name__)


@celery_app.task(name="summitflow.generate_tasks_from_scan")  # type: ignore[untyped-decorator]
def generate_tasks_from_scan(project_id: str) -> dict[str, Any]:
    """Generate refactoring tasks from Explorer scan results.

    Fetches files identified as refactoring candidates by the Explorer
    and creates SummitFlow tasks for each (if not already tracked).

    Args:
        project_id: Project to generate tasks for

    Returns:
        Dict with created_count, scanned_count, skipped_count
    """
    try:
        # Get refactor targets from Explorer
        result = get_refactor_targets(project_id, limit=20)
        targets = result.get("targets", [])

        created = 0
        scanned = 0
        skipped = 0

        for target in targets:
            scanned += 1
            file_path = target.get("path", "")
            priority = target.get("priority", "medium")
            reason = target.get("reason", "High complexity")
            complexity = target.get("complexity_score", 0)
            lines = target.get("lines_of_code", 0)

            # Skip if task already exists for this file
            if task_store.task_exists_for_file(project_id, file_path):
                skipped += 1
                continue

            # Classify tier based on complexity
            if complexity > 15 or lines > 500:
                tier = 3  # Opus
            elif complexity > 10 or lines > 300:
                tier = 2  # Sonnet
            else:
                tier = 1  # Haiku

            # Create task title
            title = f"Refactor: {reason} in {file_path.split('/')[-1]}"

            # Create the task
            description = (
                f"Auto-generated from Explorer scan.\n\n"
                f"File: {file_path}\n"
                f"Complexity: {complexity:.1f}\n"
                f"Lines: {lines}\n"
                f"Priority: {priority}"
            )

            # Create QA issue first (for self-healing linkage)
            issue_id = qa_storage.upsert_issue(
                project_id=project_id,
                issue_type="complexity",
                file_path=file_path,
                title=f"High complexity in {file_path.split('/')[-1]}",
                severity="high" if complexity > 15 else "medium",
                description=f"Complexity: {complexity:.1f}, Lines: {lines}",
                metadata={
                    "complexity_score": complexity,
                    "lines_of_code": lines,
                    "reason": reason,
                },
            )

            task = task_store.create_task(
                project_id=project_id,
                title=title,
                description=description,
                priority=2 if priority == "high" else 3,
                task_type="refactor",
                tier=tier,
            )

            if task:
                task_id = task["id"]

                # Link task to QA issue for self-healing
                link_issue_to_task(issue_id, task_id)

                category = "backend" if file_path.endswith(".py") else "frontend"
                is_frontend = category == "frontend"

                # Create task_spirit with objective, done_when, and auto-approve
                objective = (
                    f"Refactor {file_path} to reduce complexity from {complexity:.1f} "
                    f"and improve maintainability while preserving all existing behavior."
                )
                done_when = [
                    "All quality gates pass (ruff, mypy, pytest)",
                    f"File complexity score reduced (current: {complexity:.1f})",
                    "No regressions - all existing tests pass",
                ]
                if is_frontend:
                    done_when.append("No console errors in browser")

                create_task_spirit(
                    task_id=task_id,
                    objective=objective,
                    spirit_anti="Do NOT change external behavior. Do NOT rename public APIs without updating all callers.",
                    done_when=done_when,
                    complexity="SIMPLE",
                )
                # Auto-approve plan for SIMPLE auto-generated tasks
                approve_plan(task_id, approved_by="auto-generated")

                # Create acceptance criteria with verification commands
                with get_connection() as conn:
                    # Criterion 1: Ruff lint passes
                    create_task_criterion(
                        conn=conn,
                        task_id=task_id,
                        criterion="Ruff linting passes with no errors",
                        category="quality",
                        verify_by="test",
                        verify_command="dt ruff",
                        expected_output="LINT:OK",
                    )

                    # Criterion 2: Mypy type check passes
                    create_task_criterion(
                        conn=conn,
                        task_id=task_id,
                        criterion="Mypy type checking passes",
                        category="quality",
                        verify_by="test",
                        verify_command="dt mypy",
                        expected_output="TYPES:OK",
                    )

                    # Criterion 3: Pytest passes
                    create_task_criterion(
                        conn=conn,
                        task_id=task_id,
                        criterion="All tests pass",
                        category="correctness",
                        verify_by="test",
                        verify_command="dt pytest",
                        expected_output="TEST:OK",
                    )

                    # Criterion 4: Frontend - browser check (if applicable)
                    if is_frontend:
                        create_task_criterion(
                            conn=conn,
                            task_id=task_id,
                            criterion="No console errors in browser",
                            category="correctness",
                            verify_by="agent",
                            verify_command="ba check http://localhost:3001 --no-errors",
                            expected_output="exit code 0",
                        )

                    conn.commit()

                # Create subtask via normalized table
                subtask_data = [
                    {
                        "subtask_id": "1.1",
                        "phase": category,
                        "description": f"Refactor {file_path} - {reason}",
                    }
                ]
                created_subtasks = bulk_create_subtasks(task_id, subtask_data)

                # Create steps for the subtask
                if created_subtasks:
                    subtask_full_id = created_subtasks[0]["id"]
                    step_descriptions = [
                        f"Analyze {file_path} for refactoring opportunities",
                        f"Apply refactoring to reduce complexity (current: {complexity:.1f})",
                        "Run dt --check to verify all quality gates pass",
                        "Commit changes with descriptive message",
                    ]
                    bulk_create_steps(subtask_full_id, step_descriptions)

                created += 1
                logger.info(
                    f"Created task {task_id} with spirit+criteria, linked to issue {issue_id}: {title}"
                )

        logger.info(
            f"Task generation complete for {project_id}: "
            f"created={created}, scanned={scanned}, skipped={skipped}"
        )

        return {
            "created_count": created,
            "scanned_count": scanned,
            "skipped_count": skipped,
        }

    except Exception as e:
        logger.error(f"Error generating tasks from scan: {e}")
        return {"error": str(e), "created_count": 0, "scanned_count": 0, "skipped_count": 0}


@celery_app.task(name="summitflow.generate_bug_tasks")  # type: ignore[untyped-decorator]
def generate_bug_tasks(project_id: str) -> dict[str, Any]:
    """Generate bug tasks from error observations.

    DEPRECATED: This task is disabled because auto-generating tasks from error
    observations was too noisy. Most captured errors are environmental (wrong
    connection string), transient (build cache), or pre-existing (not new bugs).

    Real bugs should be discovered during actual work and created manually
    with proper context.

    Args:
        project_id: Project to generate tasks for

    Returns:
        Dict with created_count, errors_scanned, skipped_count
    """
    # Return early - this task is disabled
    # Memory system removed - observations no longer available
    logger.info(f"generate_bug_tasks disabled for {project_id}")
    return {"status": "disabled", "reason": "Task deprecated - memory system removed"}


@celery_app.task(name="summitflow.cleanup_stale_tasks")  # type: ignore[untyped-decorator]
def cleanup_stale_tasks(max_age_days: int = 30) -> dict[str, Any]:
    """Archive auto-generated tasks that have been pending without activity.

    Tasks are considered stale if:
    - Status is 'pending'
    - Has 'auto-generated' label
    - Created more than max_age_days ago
    - No recent updates

    Stale tasks are moved to 'cancelled' status to clear the backlog
    while preserving them for audit purposes.

    Args:
        max_age_days: Number of days without activity to consider stale

    Returns:
        Dict with cancelled_count and skipped_count
    """
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
                task_store.update_task(
                    task_id,
                    status="cancelled",
                    progress_log=(
                        f"Auto-cancelled: No activity for {max_age_days}+ days. "
                        "Stale auto-generated task archived."
                    ),
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
