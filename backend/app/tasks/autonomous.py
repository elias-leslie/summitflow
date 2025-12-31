"""Autonomous task execution Celery tasks.

This module provides Celery tasks for autonomous code execution:
- reset_expired_task_claims: Clean up stale task locks
- generate_tasks_from_scan: Create tasks from Explorer refactor targets
- generate_bug_tasks: Create bug tasks from error observations
- autonomous_work_pickup: Pick up and execute eligible tasks
- review_pending_tasks: Opus review gate for pending_review tasks
"""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.storage import tasks as task_store
from app.storage.explorer_analysis import get_refactor_targets

logger = logging.getLogger(__name__)


@celery_app.task(name="summitflow.reset_expired_task_claims")  # type: ignore[misc]
def reset_expired_task_claims() -> dict[str, int | str]:
    """Reset tasks with expired claim locks.

    Finds tasks where:
    - status is 'running'
    - lock_expires_at has passed
    - claimed_by is set

    Resets them to 'pending' with cleared claim fields.

    Returns:
        Dict with reset_count
    """
    try:
        count = task_store.reset_expired_claims()
        if count > 0:
            logger.info(f"Reset {count} expired task claims")
        return {"reset_count": count}
    except Exception as e:
        logger.error(f"Error resetting expired claims: {e}")
        return {"error": str(e), "reset_count": 0}


@celery_app.task(name="summitflow.generate_tasks_from_scan")  # type: ignore[misc]
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

            # Generate simple plan_content
            plan_content = {
                "tasks": [
                    {
                        "id": "1.1",
                        "category": "backend" if file_path.endswith(".py") else "frontend",
                        "description": f"Refactor {file_path} - {reason}",
                        "steps": [
                            f"Analyze {file_path} for refactoring opportunities",
                            f"Apply refactoring to reduce complexity (current: {complexity:.1f})",
                            "Run tests to verify no regressions",
                            "Commit changes with descriptive message",
                        ],
                        "passes": False,
                    }
                ],
                "current_task_id": "1.1",
                "context": {
                    "affected_files": [file_path],
                    "capability_id": None,
                    "source": "explorer_scan",
                    "metrics": {
                        "complexity_score": complexity,
                        "lines_of_code": lines,
                    },
                },
            }

            # Create the task (without plan_content)
            description = (
                f"Auto-generated from Explorer scan.\n\n"
                f"File: {file_path}\n"
                f"Complexity: {complexity:.1f}\n"
                f"Lines: {lines}\n"
                f"Priority: {priority}"
            )

            task = task_store.create_task(
                project_id=project_id,
                title=title,
                description=description,
                priority=2 if priority == "high" else 3,
                task_type="task",
                labels=["auto-generated", f"tier:{tier}"],
            )

            if task:
                # Update with plan_content (needs separate call)
                task_store.update_task(task["id"], plan_content=plan_content)
                created += 1
                logger.info(f"Created task {task['id']}: {title}")

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


@celery_app.task(name="summitflow.generate_bug_tasks")  # type: ignore[misc]
def generate_bug_tasks(project_id: str) -> dict[str, Any]:
    """Generate bug tasks from error observations.

    Fetches high-confidence error observations from the memory system
    and creates bug tasks for each (if not already tracked).

    Args:
        project_id: Project to generate tasks for

    Returns:
        Dict with created_count, errors_scanned, skipped_count
    """
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
            observation_id = str(error.get("id", ""))  # Convert UUID to string

            if not error_title:
                skipped += 1
                continue

            # Skip if bug task already exists for this error
            if task_store.bug_task_exists_for_error(project_id, error_title):
                skipped += 1
                logger.debug(f"Bug task already exists for: {error_title[:50]}...")
                continue

            # Create task title (prefix with "Fix:")
            title = f"Fix: {error_title[:80]}"

            # Determine category based on affected files
            category = "backend"
            if files:
                first_file = files[0] if isinstance(files[0], str) else files[0].get("path", "")
                if any(ext in first_file for ext in [".tsx", ".ts", ".jsx", ".js"]):
                    category = "frontend"

            # Generate plan_content with investigation and fix tasks
            plan_content = {
                "tasks": [
                    {
                        "id": "1.1",
                        "category": category,
                        "description": f"Investigate: {error_title[:60]}",
                        "steps": [
                            "Read the error observation narrative for context",
                            f"Examine affected files: {', '.join(files[:3]) if files else 'N/A'}",
                            "Identify root cause of the error",
                            "Document findings in progress log",
                        ],
                        "passes": False,
                    },
                    {
                        "id": "1.2",
                        "category": category,
                        "description": f"Fix: {error_title[:60]}",
                        "steps": [
                            "Implement fix based on investigation findings",
                            "Run tests to verify fix works",
                            "Ensure no regressions introduced",
                            "Commit changes with descriptive message",
                        ],
                        "passes": False,
                    },
                ],
                "current_task_id": "1.1",
                "context": {
                    "affected_files": files[:5] if files else [],
                    "capability_id": None,
                    "source": "error_observation",
                    "observation_id": observation_id,
                    "confidence": confidence,
                },
            }

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

            # Create the bug task
            task = task_store.create_task(
                project_id=project_id,
                title=title,
                description=description,
                priority=2,  # Default medium priority for auto-generated bugs
                task_type="bug",
                labels=["auto-generated", "bug", "tier:2"],
            )

            if task:
                # Update with plan_content
                task_store.update_task(task["id"], plan_content=plan_content)
                created += 1
                logger.info(f"Created bug task {task['id']}: {title[:60]}...")

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
