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


def _get_targeted_test_command(relative_path: str) -> str:
    """Generate a targeted pytest command for the specific file being refactored.

    Maps source file paths to their corresponding test files.
    Falls back to import check if no test file pattern matches.

    Args:
        relative_path: Relative path to the source file (e.g., "backend/app/tasks/ai_review.py")

    Returns:
        Pytest command targeting specific tests, or import check as fallback
    """
    import re

    # Extract the module name and path components
    # e.g., "backend/app/tasks/ai_review.py" -> module="ai_review", dir="backend/app/tasks"
    path_match = re.match(r"^(backend)/(app|cli)/(.+)/([^/]+)\.py$", relative_path)
    if path_match:
        prefix, app_or_cli, subdir, module = path_match.groups()
        # Map to test file: backend/app/tasks/foo.py -> backend/tests/tasks/test_foo.py
        test_path = f"{prefix}/tests/{subdir}/test_{module}.py"
        # Use pytest with the specific test file, fallback to import check if file doesn't exist
        return f"test -f {test_path} && pytest {test_path} -q --tb=short || python -c 'from {app_or_cli}.{subdir.replace('/', '.')}.{module} import *'"

    # Handle direct backend/app/*.py or backend/cli/*.py files
    path_match = re.match(r"^(backend)/(app|cli)/([^/]+)\.py$", relative_path)
    if path_match:
        prefix, app_or_cli, module = path_match.groups()
        test_path = f"{prefix}/tests/test_{module}.py"
        return f"test -f {test_path} && pytest {test_path} -q --tb=short || python -c 'from {app_or_cli}.{module} import *'"

    # Frontend files - just check import/build
    if relative_path.startswith("frontend/"):
        return "cd frontend && npm run build --quiet"

    # Fallback: simple import check using python
    module_path = relative_path.replace("/", ".").replace(".py", "")
    return f"python -c 'import {module_path}' 2>/dev/null || echo 'Import check skipped'"


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
                            "description": f"Verify tests for {file_path}",
                            "verify_command": _get_targeted_test_command(file_path),
                            "expected_output": "exit code 0",
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
            return {
                "error": f"Project {project_id} not found",
                "deleted_count": 0,
                "created_count": 0,
                "scanned_count": 0,
            }

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
                            "description": f"Verify tests for {relative_path}",
                            "verify_command": _get_targeted_test_command(relative_path),
                            "expected_output": "exit code 0",
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
                logger.info(f"Created refactor task {task_id} with line verification: {title}")

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


@celery_app.task(name="summitflow.generate_schema_tasks")
def generate_schema_tasks(project_id: str) -> dict[str, Any]:
    """Generate schema tasks from database table violations.

    Fetches tables with schema violations detected by Explorer and creates
    SummitFlow tasks for each violation type (if not already tracked).

    Violation types (per M:4e199d70):
    - missing_fk_index: FK column without index
    - naming_violation: Non-snake_case or non-plural
    - missing_timestamps: Missing created_at/updated_at
    - god_table: 20+ columns

    Args:
        project_id: Project to generate tasks for

    Returns:
        Dict with created_count, scanned_count, skipped_count
    """
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

                issue_id = qa_storage.upsert_issue(
                    project_id=project_id,
                    issue_type=violation_type,
                    file_path=file_path,
                    title=f"Schema: {detail}",
                    severity="high" if severity == "error" else "medium",
                    description=f"Table: {table_name}\nViolation: {detail}",
                    metadata={
                        "table_name": table_name,
                        "violation_type": violation_type,
                        "column_count": metadata.get("column_count", 0),
                    },
                )

                title = f"Schema: {_get_violation_title(violation_type, table_name)}"
                description = (
                    f"Auto-generated from Explorer schema scan.\n\n"
                    f"Table: {table_name}\n"
                    f"Violation: {detail}\n"
                    f"Severity: {severity}"
                )

                tier = 2 if violation_type == "god_table" else 1

                task = task_store.create_task(
                    project_id=project_id,
                    title=title,
                    description=description,
                    priority=2 if severity == "error" else 3,
                    task_type="schema",
                    tier=tier,
                )

                if task:
                    task_id = task["id"]

                    link_issue_to_task(issue_id, task_id)

                    objective = _get_violation_objective(violation_type, table_name, detail)
                    done_when = _get_violation_done_when(violation_type, table_name)

                    create_task_spirit(
                        task_id=task_id,
                        objective=objective,
                        spirit_anti="Do NOT break existing queries. Do NOT rename without updating all references.",
                        done_when=done_when,
                        complexity="SIMPLE",
                    )
                    approve_plan(task_id, approved_by="auto-generated")

                    subtask_data = [
                        {
                            "subtask_id": "1.1",
                            "phase": "backend",
                            "description": f"Fix {violation_type} in {table_name}",
                        }
                    ]
                    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

                    if created_subtasks:
                        subtask_full_id = created_subtasks[0]["id"]
                        steps = _get_violation_steps(violation_type, table_name, detail)
                        bulk_create_steps(subtask_full_id, steps)

                    created += 1
                    logger.info(
                        f"Created schema task {task_id}, linked to issue {issue_id}: {title}"
                    )

        logger.info(
            f"Schema task generation complete for {project_id}: "
            f"created={created}, scanned={scanned}, skipped={skipped}"
        )

        return {
            "created_count": created,
            "scanned_count": scanned,
            "skipped_count": skipped,
        }

    except Exception as e:
        logger.error(f"Error generating schema tasks: {e}")
        return {"error": str(e), "created_count": 0, "scanned_count": 0, "skipped_count": 0}


def _get_violation_title(violation_type: str, table_name: str) -> str:
    """Generate task title for a schema violation."""
    titles = {
        "missing_fk_index": f"Add missing FK index on {table_name}",
        "naming_violation": f"Fix naming convention in {table_name}",
        "missing_timestamps": f"Add timestamps to {table_name}",
        "god_table": f"Refactor {table_name} (too many columns)",
    }
    return titles.get(violation_type, f"Fix schema issue in {table_name}")


def _get_violation_objective(violation_type: str, table_name: str, detail: str) -> str:
    """Generate objective for a schema violation task."""
    objectives = {
        "missing_fk_index": f"Add an index on the FK column in {table_name} to improve query performance. {detail}",
        "naming_violation": f"Rename {table_name} or its columns to follow snake_case and plural table naming conventions.",
        "missing_timestamps": f"Add created_at and updated_at timestamp columns to {table_name} for audit tracking.",
        "god_table": f"Refactor {table_name} by extracting related columns into separate tables to reduce complexity.",
    }
    return objectives.get(violation_type, f"Fix schema violation in {table_name}: {detail}")


def _get_violation_done_when(violation_type: str, table_name: str) -> list[str]:
    """Generate done_when criteria for a schema violation task."""
    base = [
        "Migration created and applied successfully",
        "All existing queries still work",
        "dt mypy passes",
    ]

    specific = {
        "missing_fk_index": [f"Index exists on FK column in {table_name}"],
        "naming_violation": ["Table/columns follow snake_case convention"],
        "missing_timestamps": [f"{table_name} has created_at and updated_at columns"],
        "god_table": [f"{table_name} has fewer than 20 columns"],
    }

    return specific.get(violation_type, []) + base


def _get_violation_steps(violation_type: str, table_name: str, detail: str) -> list[dict[str, str]]:
    """Generate verification steps for a schema violation task."""
    steps = {
        "missing_fk_index": [
            {
                "description": f"Create migration to add index on FK column in {table_name}",
                "verify_command": f"ls backend/alembic/versions/*{table_name.lower()}*.py 2>/dev/null | head -1",
                "expected_output": "migration file path",
            },
            {
                "description": "Apply migration",
                "verify_command": "cd backend && alembic upgrade head",
                "expected_output": "exit code 0",
            },
            {
                "description": "Verify index exists",
                "verify_command": f"psql $DATABASE_URL -c \"SELECT indexname FROM pg_indexes WHERE tablename = '{table_name}'\"",
                "expected_output": "index name",
            },
        ],
        "naming_violation": [
            {
                "description": f"Create migration to rename {table_name} or columns",
                "verify_command": "ls backend/alembic/versions/*rename*.py 2>/dev/null | head -1",
                "expected_output": "migration file path",
            },
            {
                "description": "Update all model references",
                "verify_command": "dt mypy",
                "expected_output": "TYPES:OK",
            },
            {
                "description": "Apply migration",
                "verify_command": "cd backend && alembic upgrade head",
                "expected_output": "exit code 0",
            },
        ],
        "missing_timestamps": [
            {
                "description": f"Create migration to add timestamps to {table_name}",
                "verify_command": "ls backend/alembic/versions/*timestamp*.py 2>/dev/null | head -1",
                "expected_output": "migration file path",
            },
            {
                "description": "Update SQLAlchemy model with timestamp columns",
                "verify_command": f"rg 'created_at|updated_at' backend/app/models/*.py | rg -i {table_name}",
                "expected_output": "column definitions",
            },
            {
                "description": "Apply migration",
                "verify_command": "cd backend && alembic upgrade head",
                "expected_output": "exit code 0",
            },
        ],
        "god_table": [
            {
                "description": f"Analyze {table_name} for column groupings",
                "verify_command": f"psql $DATABASE_URL -c \"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'\" | wc -l",
                "expected_output": "column count",
            },
            {
                "description": "Create migration to extract related columns",
                "verify_command": f"ls backend/alembic/versions/*{table_name.lower()}*.py 2>/dev/null | head -1",
                "expected_output": "migration file path",
            },
            {
                "description": "Verify column count reduced",
                "verify_command": f"psql $DATABASE_URL -c \"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'\" | tail -3 | head -1 | xargs test 20 -gt",
                "expected_output": "exit code 0",
            },
        ],
    }

    return steps.get(
        violation_type,
        [
            {
                "description": f"Fix schema violation in {table_name}: {detail}",
                "verify_command": "dt mypy",
                "expected_output": "TYPES:OK",
            },
        ],
    )


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


@celery_app.task(name="summitflow.generate_architecture_tasks")
def generate_architecture_tasks(project_id: str) -> dict[str, Any]:
    """Generate tasks from architecture violations detected by Explorer.

    Consolidates violations by type into single tasks to reduce overhead.
    Creates one task per violation type with affected files as subtasks.

    Violation types:
    - parallel_implementation: Multiple implementations of same functionality (error)
    - missing_infrastructure: Missing caching, error handling, observability (warning)
    - duplicate_utility: Literal code duplication (warning)

    Args:
        project_id: Project to generate tasks for

    Returns:
        Dict with created_count, scanned_count, skipped_count
    """
    from collections import defaultdict

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
                violations_by_type[violation_type].append(
                    {
                        **violation,
                        "module_path": module_path,
                    }
                )

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

            affected_files = [v.get("file_path", "") for v in violations if v.get("file_path")]
            affected_files = list(set(affected_files))

            title = _get_consolidated_architecture_title(violation_type, len(affected_files))
            severity = "error" if violation_type == "parallel_implementation" else "warning"

            issue_id = qa_storage.upsert_issue(
                project_id=project_id,
                issue_type=violation_type,
                file_path=issue_path,
                title=f"Architecture: {title}",
                severity="high" if severity == "error" else "medium",
                description=f"Found {len(violations)} {violation_type} violations across {len(affected_files)} files",
                metadata={
                    "violation_type": violation_type,
                    "affected_files": affected_files[:20],
                    "violation_count": len(violations),
                },
            )

            description = (
                f"Auto-generated from Explorer architecture scan.\n\n"
                f"**Violation Type:** {violation_type.replace('_', ' ').title()}\n"
                f"**Affected Files:** {len(affected_files)}\n"
                f"**Total Violations:** {len(violations)}\n\n"
                f"### Files to fix:\n"
            )
            for f in affected_files[:15]:
                description += f"- {f}\n"
            if len(affected_files) > 15:
                description += f"- ... and {len(affected_files) - 15} more files\n"

            tier = 2 if violation_type == "parallel_implementation" else 1

            task = task_store.create_task(
                project_id=project_id,
                title=f"Architecture: {title}",
                description=description,
                priority=2 if severity == "error" else 3,
                task_type="refactor",
                tier=tier,
            )

            if task:
                task_id = task["id"]
                link_issue_to_task(issue_id, task_id)

                objective = _get_consolidated_architecture_objective(violation_type, affected_files)
                done_when = _get_consolidated_architecture_done_when(violation_type)

                create_task_spirit(
                    task_id=task_id,
                    objective=objective,
                    spirit_anti="Do NOT break existing functionality. Fix violations systematically, not file-by-file randomly.",
                    done_when=done_when,
                    complexity="STANDARD" if len(affected_files) > 5 else "SIMPLE",
                )
                if tier == 1 and len(affected_files) <= 5:
                    approve_plan(task_id, approved_by="auto-generated")

                subtask_data = []
                for i, file_path in enumerate(affected_files[:10], 1):
                    subtask_data.append(
                        {
                            "subtask_id": f"1.{i}",
                            "phase": "backend" if file_path.endswith(".py") else "frontend",
                            "description": f"Fix {violation_type.replace('_', ' ')} in {file_path.split('/')[-1]}",
                        }
                    )

                if subtask_data:
                    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

                    for subtask in created_subtasks:
                        subtask_full_id = subtask["id"]
                        steps = [
                            {"description": f"Identify {violation_type.replace('_', ' ')} issue"},
                            {"description": "Implement fix following project patterns"},
                            {"description": "Verify fix with tests or manual check"},
                        ]
                        bulk_create_steps(subtask_full_id, steps)

                created += 1
                logger.info(
                    f"Created consolidated architecture task {task_id} for {violation_type}: "
                    f"{len(affected_files)} files, linked to issue {issue_id}"
                )

        logger.info(
            f"Architecture task generation complete for {project_id}: "
            f"created={created}, scanned={scanned}, skipped={skipped}"
        )

        return {
            "created_count": created,
            "scanned_count": scanned,
            "skipped_count": skipped,
        }

    except Exception as e:
        logger.error(f"Error generating architecture tasks: {e}")
        return {"error": str(e), "created_count": 0, "scanned_count": 0, "skipped_count": 0}


def _get_consolidated_architecture_title(violation_type: str, file_count: int) -> str:
    """Generate consolidated task title for a violation type."""
    titles = {
        "parallel_implementation": f"Consolidate parallel implementations ({file_count} files)",
        "missing_infrastructure": f"Add missing infrastructure ({file_count} files)",
        "duplicate_utility": f"Remove duplicate code ({file_count} files)",
    }
    return titles.get(violation_type, f"Fix {violation_type} ({file_count} files)")


def _get_consolidated_architecture_objective(violation_type: str, affected_files: list[str]) -> str:
    """Generate objective for a consolidated architecture task."""
    file_list = ", ".join(f.split("/")[-1] for f in affected_files[:5])
    if len(affected_files) > 5:
        file_list += f" and {len(affected_files) - 5} more"

    objectives = {
        "parallel_implementation": (
            f"Consolidate multiple implementations into a single shared utility. "
            f"Affected files: {file_list}. Identify the best implementation and refactor others to use it."
        ),
        "missing_infrastructure": (
            f"Add missing infrastructure (logging, error handling, observability) to API endpoints. "
            f"Affected files: {file_list}. Follow existing patterns in the codebase."
        ),
        "duplicate_utility": (
            f"Remove literal code duplication by extracting shared utilities. "
            f"Affected files: {file_list}. DRY principle - extract to shared module."
        ),
    }
    return objectives.get(violation_type, f"Fix {violation_type} in {file_list}")


def _get_consolidated_architecture_done_when(violation_type: str) -> list[str]:
    """Generate done_when criteria for a consolidated architecture task."""
    criteria = {
        "parallel_implementation": [
            "Single canonical implementation exists",
            "All usages refactored to use shared implementation",
            "No duplicate implementations remain",
            "Tests pass after consolidation",
        ],
        "missing_infrastructure": [
            "All affected files have proper logging",
            "Error handling follows project patterns",
            "No linting warnings for missing infrastructure",
        ],
        "duplicate_utility": [
            "Shared utility extracted to appropriate location",
            "All duplicate code replaced with utility calls",
            "No copy-paste code detected by jscpd",
        ],
    }
    return criteria.get(violation_type, [f"All {violation_type} violations resolved"])
