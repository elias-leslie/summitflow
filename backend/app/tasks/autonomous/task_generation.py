"""Celery tasks for generating tasks from scans and observations."""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.services.task_issue_mapper import link_issue_to_task
from app.storage import qa_issues as qa_storage
from app.storage import tasks as task_store
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.steps import bulk_create_steps
from app.storage.subtasks import bulk_create_subtasks

from .task_filters import is_blocklisted_error

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
                task_type="task",
                labels=["auto-generated", f"tier:{tier}"],
                tier=tier,
            )

            if task:
                task_id = task["id"]

                # Link task to QA issue for self-healing
                link_issue_to_task(issue_id, task_id)

                category = "backend" if file_path.endswith(".py") else "frontend"

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
                        "Run tests to verify no regressions",
                        "Commit changes with descriptive message",
                    ]
                    bulk_create_steps(subtask_full_id, step_descriptions)

                created += 1
                logger.info(f"Created task {task_id} linked to issue {issue_id}: {title}")

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
    logger.info(f"generate_bug_tasks disabled for {project_id}")
    return {"status": "disabled", "reason": "Task deprecated - too noisy"}
    # Import here to avoid circular imports
    from app.storage.memory import query_observations

    try:
        # Fetch recent high-confidence error observations
        errors = query_observations(
            project_id=project_id,
            observation_type="error",
            min_confidence=0.8,
            days=7,
            limit=20,
        )

        created = 0
        scanned = 0
        skipped = 0

        for error in errors:
            scanned += 1
            error_title = error.get("title", "")
            narrative = error.get("narrative", "")
            files = error.get("files", [])
            confidence = error.get("confidence", 0.0)

            if not error_title:
                skipped += 1
                continue

            # Skip blocklisted errors (environmental/transient, not real bugs)
            if is_blocklisted_error(error_title):
                skipped += 1
                logger.debug(f"Blocklisted error pattern: {error_title[:50]}...")
                continue

            # Skip if bug task already exists for this error
            if task_store.bug_task_exists_for_error(project_id, error_title):
                skipped += 1
                logger.debug(f"Bug task already exists for: {error_title[:50]}...")
                continue

            # Create task title (prefix with "Fix:")
            title = f"Fix: {error_title[:80]}"

            # Determine category and first file based on affected files
            category = "backend"
            first_file: str | None = None
            if files:
                first_file = files[0] if isinstance(files[0], str) else files[0].get("path", "")
                if first_file and any(ext in first_file for ext in [".tsx", ".ts", ".jsx", ".js"]):
                    category = "frontend"

            # Build description from narrative
            description = (
                f"Auto-generated from error observation.\n\n"
                f"**Error:** {error_title}\n\n"
                f"**Confidence:** {confidence:.0%}\n\n"
            )
            if narrative:
                description += f"**Details:**\n{narrative[:500]}\n\n"
            if files:
                description += "**Affected Files:**\n" + "\n".join(f"- {f}" for f in files[:5])

            # Create QA issue first (for self-healing linkage)
            issue_id = qa_storage.upsert_issue(
                project_id=project_id,
                issue_type="error",
                file_path=first_file,
                title=error_title[:200],
                severity="high" if confidence >= 0.9 else "medium",
                description=narrative[:500] if narrative else None,
                metadata={
                    "confidence": confidence,
                    "affected_files": files[:10] if files else [],
                    "observation_id": error.get("id"),
                },
            )

            # Create the bug task
            task = task_store.create_task(
                project_id=project_id,
                title=title,
                description=description,
                priority=2,  # Default medium priority for auto-generated bugs
                task_type="bug",
                labels=["auto-generated", "bug", "tier:2"],
                tier=2,  # Bug tasks default to tier 2 (requires review)
            )

            if task:
                task_id = task["id"]

                # Link task to QA issue for self-healing
                link_issue_to_task(issue_id, task_id)

                # Create subtasks via normalized table
                subtask_data = [
                    {
                        "subtask_id": "1.1",
                        "phase": category,
                        "description": f"Investigate: {error_title[:60]}",
                    },
                    {
                        "subtask_id": "1.2",
                        "phase": category,
                        "description": f"Fix: {error_title[:60]}",
                    },
                ]
                created_subtasks = bulk_create_subtasks(task_id, subtask_data)

                # Create steps for each subtask
                if len(created_subtasks) >= 2:
                    # Investigation steps
                    investigation_steps = [
                        "Read the error observation narrative for context",
                        f"Examine affected files: {', '.join(files[:3]) if files else 'N/A'}",
                        "Identify root cause of the error",
                        "Document findings in progress log",
                    ]
                    bulk_create_steps(created_subtasks[0]["id"], investigation_steps)

                    # Fix steps
                    fix_steps = [
                        "Implement fix based on investigation findings",
                        "Run tests to verify fix works",
                        "Ensure no regressions introduced",
                        "Commit changes with descriptive message",
                    ]
                    bulk_create_steps(created_subtasks[1]["id"], fix_steps)

                created += 1
                logger.info(
                    f"Created bug task {task_id} linked to issue {issue_id}: {title[:60]}..."
                )

        logger.info(
            f"Bug task generation complete for {project_id}: "
            f"created={created}, scanned={scanned}, skipped={skipped}"
        )

        return {
            "created_count": created,
            "errors_scanned": scanned,
            "skipped_count": skipped,
        }

    except Exception as e:
        logger.error(f"Error generating bug tasks: {e}")
        return {"error": str(e), "created_count": 0, "errors_scanned": 0, "skipped_count": 0}
