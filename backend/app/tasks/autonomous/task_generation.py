"""Celery tasks for generating tasks from Explorer scans."""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.services.task_issue_mapper import link_issue_to_task
from app.storage import log_task_event
from app.storage import qa_issues as qa_storage
from app.storage import tasks as task_store
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.projects import get_project_root_path
from app.storage.steps import bulk_create_steps
from app.storage.subtasks import bulk_create_subtasks
from app.storage.task_spirit import approve_plan, create_task_spirit
from app.storage.tasks import delete_task
from app.storage.tasks.queries import list_tasks

logger = logging.getLogger(__name__)


def _delete_existing_refactor_tasks(project_id: str) -> int:
    """Delete all existing refactor tasks for a project.

    This ensures a clean slate before generating new refactor tasks from scan.
    Prevents duplicate tasks and ensures tasks reflect current codebase state.

    Args:
        project_id: Project to clean up

    Returns:
        Number of tasks deleted
    """
    # Get all refactor tasks for the project
    refactor_tasks = list_tasks(
        project_id=project_id,
        task_type_filter="refactor",
        limit=500,  # High limit to get all
    )

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


def _calculate_target_lines(current_lines: int) -> int:
    """Calculate target line count for refactoring.

    Args:
        current_lines: Current file line count

    Returns:
        Target line count (always less than current)
    """
    if current_lines > 1000:
        return 500  # Large files should get to 500
    elif current_lines > 500:
        return 300  # Medium-large files should get to 300
    elif current_lines > 300:
        return 200  # Medium files should get to 200
    else:
        return 150  # Small files - modest reduction


@celery_app.task(name="summitflow.generate_tasks_from_scan")
def generate_tasks_from_scan(project_id: str) -> dict[str, Any]:
    """Generate refactoring tasks from Explorer scan results.

    Fetches files identified as refactoring candidates by the Explorer
    and creates SummitFlow tasks for each (if not already tracked).

    NOTE: Does NOT delete existing tasks. Use regenerate_refactor_tasks() for
    a clean-slate approach that deletes existing tasks first.

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

            # Calculate target line count for verification
            target_lines = _calculate_target_lines(lines)

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
                    f"Refactor {file_path} to reduce line count from {lines} to <{target_lines} lines "
                    f"while preserving all existing behavior."
                )
                done_when = [
                    "All quality gates pass (ruff, mypy, pytest)",
                    f"File line count reduced to <{target_lines} lines (current: {lines})",
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

                # Create subtask via normalized table
                subtask_data = [
                    {
                        "subtask_id": "1.1",
                        "phase": category,
                        "description": f"Refactor {file_path} - {reason}",
                    }
                ]
                created_subtasks = bulk_create_subtasks(task_id, subtask_data)

                # Create steps with verification commands for agent feedback loop
                if created_subtasks:
                    subtask_full_id = created_subtasks[0]["id"]
                    steps = [
                        {
                            "description": f"Analyze {file_path} for refactoring opportunities",
                            "verify_command": f"test -f {file_path}",
                            "expected_output": "exit code 0",
                        },
                        {
                            "description": f"Split/refactor to reduce line count from {lines} to <{target_lines}",
                            "verify_command": f"test $(wc -l < {file_path}) -lt {target_lines}",
                            "expected_output": "exit code 0",
                        },
                        {
                            "description": "Verify ruff linting passes",
                            "verify_command": "dt ruff",
                            "expected_output": "LINT:OK",
                        },
                        {
                            "description": "Verify mypy type checking passes",
                            "verify_command": "dt mypy",
                            "expected_output": "TYPES:OK",
                        },
                        {
                            "description": "Verify all tests pass",
                            "verify_command": "dt pytest",
                            "expected_output": "TEST:OK",
                        },
                    ]
                    # Add browser check for frontend files
                    if is_frontend:
                        steps.append(
                            {
                                "description": "Verify no console errors in browser",
                                "verify_command": "agent-browser open http://localhost:3001 && agent-browser wait --load networkidle",
                                "expected_output": "exit code 0",
                            }
                        )
                    steps.append(
                        {
                            "description": "Commit changes with descriptive message",
                            "verify_command": "git diff --cached --quiet || git log -1 --oneline",
                            "expected_output": "exit code 0 or commit hash",
                        }
                    )
                    bulk_create_steps(subtask_full_id, steps)

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


@celery_app.task(name="summitflow.regenerate_refactor_tasks")
def regenerate_refactor_tasks(project_id: str) -> dict[str, Any]:
    """Delete all existing refactor tasks and regenerate from current scan.

    This is a clean-slate approach for use by /refactor_it skill or manual
    invocation. Ensures tasks reflect the current codebase state.

    Unlike generate_tasks_from_scan (which skips existing), this:
    1. Deletes ALL existing refactor tasks for the project
    2. Runs a fresh scan to identify targets
    3. Creates new tasks with proper verification commands

    Args:
        project_id: Project to regenerate tasks for

    Returns:
        Dict with deleted_count, created_count, scanned_count
    """
    try:
        # Get project root for absolute paths in verify commands
        project_root = get_project_root_path(project_id)
        if not project_root:
            logger.error(f"Project {project_id} not found or has no root_path")
            return {"error": f"Project {project_id} not found", "deleted_count": 0, "created_count": 0, "scanned_count": 0}

        # Clean slate: delete all existing refactor tasks
        deleted_count = _delete_existing_refactor_tasks(project_id)

        # Get fresh refactor targets from Explorer
        result = get_refactor_targets(project_id, limit=20)
        targets = result.get("targets", [])

        created = 0
        scanned = 0

        for target in targets:
            scanned += 1
            relative_path = target.get("path", "")
            # Build absolute path for verify commands
            file_path = f"{project_root}/{relative_path}"
            priority = target.get("priority", "medium")
            reason = target.get("reason", "High complexity")
            complexity = target.get("complexity_score", 0)
            lines = target.get("lines_of_code", 0)

            # Calculate target line count for verification
            target_lines = _calculate_target_lines(lines)

            # Classify tier based on complexity
            if complexity > 15 or lines > 500:
                tier = 3  # Opus
            elif complexity > 10 or lines > 300:
                tier = 2  # Sonnet
            else:
                tier = 1  # Haiku

            # Create task title (use filename only)
            title = f"Refactor: {reason} in {relative_path.split('/')[-1]}"

            # Create the task (show relative path for readability)
            description = (
                f"Auto-generated from Explorer scan.\n\n"
                f"File: {relative_path}\n"
                f"Lines: {lines} → target <{target_lines}\n"
                f"Complexity: {complexity:.1f}\n"
                f"Priority: {priority}"
            )

            # Create QA issue first (for self-healing linkage)
            # Use relative_path so it matches Explorer entries for auto-close
            issue_id = qa_storage.upsert_issue(
                project_id=project_id,
                issue_type="complexity",
                file_path=relative_path,
                title=f"High complexity in {relative_path.split('/')[-1]}",
                severity="high" if complexity > 15 else "medium",
                description=f"Complexity: {complexity:.1f}, Lines: {lines}",
                metadata={
                    "complexity_score": complexity,
                    "lines_of_code": lines,
                    "target_lines": target_lines,
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

                category = "backend" if relative_path.endswith(".py") else "frontend"
                is_frontend = category == "frontend"

                # Create task_spirit with objective, done_when, and auto-approve
                # Use relative_path in objective for readability
                objective = (
                    f"Refactor {relative_path} to reduce line count from {lines} to <{target_lines} lines "
                    f"while preserving all existing behavior."
                )
                done_when = [
                    "All quality gates pass (ruff, mypy, pytest)",
                    f"File line count reduced to <{target_lines} lines (current: {lines})",
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

                # Create subtask via normalized table
                subtask_data = [
                    {
                        "subtask_id": "1.1",
                        "phase": category,
                        "description": f"Refactor {relative_path} - reduce to <{target_lines} lines",
                    }
                ]
                created_subtasks = bulk_create_subtasks(task_id, subtask_data)

                # Create steps with verification commands for agent feedback loop
                # Use absolute file_path in verify_commands so they work from any directory
                if created_subtasks:
                    subtask_full_id = created_subtasks[0]["id"]
                    steps = [
                        {
                            "description": f"Analyze {relative_path} for refactoring opportunities",
                            "verify_command": f"test -f {file_path}",
                            "expected_output": "exit code 0",
                        },
                        {
                            "description": f"Split/refactor to reduce line count from {lines} to <{target_lines}",
                            "verify_command": f"test $(wc -l < {file_path}) -lt {target_lines}",
                            "expected_output": "exit code 0",
                        },
                        {
                            "description": "Verify ruff linting passes",
                            "verify_command": "dt ruff",
                            "expected_output": "LINT:OK",
                        },
                        {
                            "description": "Verify mypy type checking passes",
                            "verify_command": "dt mypy",
                            "expected_output": "TYPES:OK",
                        },
                        {
                            "description": "Verify all tests pass",
                            "verify_command": "dt pytest",
                            "expected_output": "TEST:OK",
                        },
                    ]
                    # Add browser check for frontend files
                    if is_frontend:
                        steps.append(
                            {
                                "description": "Verify no console errors in browser",
                                "verify_command": "agent-browser open http://localhost:3001 && agent-browser wait --load networkidle",
                                "expected_output": "exit code 0",
                            }
                        )
                    steps.append(
                        {
                            "description": "Commit changes with descriptive message",
                            "verify_command": "git diff --cached --quiet || git log -1 --oneline",
                            "expected_output": "exit code 0 or commit hash",
                        }
                    )
                    bulk_create_steps(subtask_full_id, steps)

                created += 1
                logger.info(
                    f"Created refactor task {task_id} with line verification: {title}"
                )

        logger.info(
            f"Refactor task regeneration complete for {project_id}: "
            f"deleted={deleted_count}, created={created}, scanned={scanned}"
        )

        return {
            "deleted_count": deleted_count,
            "created_count": created,
            "scanned_count": scanned,
        }

    except Exception as e:
        logger.error(f"Error regenerating refactor tasks: {e}")
        return {"error": str(e), "deleted_count": 0, "created_count": 0, "scanned_count": 0}


@celery_app.task(name="summitflow.generate_bug_tasks")
def generate_bug_tasks(project_id: str) -> dict[str, Any]:
    """Generate bug tasks from runtime errors.

    DEPRECATED: This task is disabled. Bug tasks are now created via the
    self-healing system (systemd journal monitor, console error capture).

    Args:
        project_id: Project to generate tasks for

    Returns:
        Dict with status and reason
    """
    logger.info(f"generate_bug_tasks disabled for {project_id}")
    return {"status": "disabled", "reason": "Use self-healing system instead"}


@celery_app.task(name="summitflow.cleanup_stale_tasks")
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
                )
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
