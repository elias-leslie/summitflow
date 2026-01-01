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
                tier=tier,
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
                tier=2,  # Bug tasks default to tier 2 (requires review)
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


# Security-sensitive directory names that require human review
SECURITY_DIRS = ["auth", "security", "payment", "credentials", "secret", "crypto", "oauth"]

# Exploratory task indicators
EXPLORATORY_KEYWORDS = ["investigate", "explore", "understand", "research", "analyze"]

# Standalone task labels that require manual execution
STANDALONE_LABELS = ["standalone", "exploratory"]


def _is_standalone(task: dict[str, Any]) -> bool:
    """Check if task is standalone (no capability linkage).

    Standalone tasks require manual execution via /do_it because they lack
    capability-driven acceptance criteria for autonomous verification.
    """
    return task.get("capability_id") is None


def _has_standalone_label(task: dict[str, Any]) -> bool:
    """Check if task has a standalone or exploratory label."""
    labels = task.get("labels") or []
    return any(label in STANDALONE_LABELS for label in labels)


def _is_security_sensitive(files: list[str]) -> bool:
    """Check if any files are in security-sensitive directories."""
    for f in files:
        parts = f.lower().split("/")
        for part in parts:
            if any(sec in part for sec in SECURITY_DIRS):
                return True
    return False


def _is_exploratory(task: dict[str, Any]) -> bool:
    """Check if task is exploratory (requires human reasoning)."""
    task_type = task.get("task_type", "")
    if task_type == "research":
        return True
    title = (task.get("title") or "").lower()
    return any(kw in title for kw in EXPLORATORY_KEYWORDS)


def _count_domains(files: list[str]) -> int:
    """Count how many domains a task affects."""
    domains = set()
    for f in files:
        if f.startswith("backend/") or f.endswith(".py"):
            domains.add("backend")
        elif f.startswith("frontend/") or f.endswith((".tsx", ".ts", ".jsx", ".js")):
            domains.add("frontend")
        elif "migration" in f or f.endswith(".sql"):
            domains.add("database")
        elif f.startswith("infra/") or f.endswith((".yaml", ".yml", ".tf")):
            domains.add("infra")
    return len(domains)


def _check_exclusion(task: dict[str, Any]) -> str | None:
    """Check if task should be excluded from autonomous execution.

    Returns:
        Exclusion reason string, or None if task is eligible
    """
    labels = task.get("labels") or []
    tier = task.get("tier") or 2

    # Get affected files from plan_content or description
    plan_content = task.get("plan_content") or {}
    context = plan_content.get("context") or {}
    affected_files = context.get("affected_files") or []

    # EXCLUDE: labels contain 'needs-tests' or 'needs-human-review'
    if "needs-tests" in labels:
        return "needs-tests label"
    if "needs-human-review" in labels:
        return "needs-human-review label"

    # EXCLUDE: standalone tasks (no capability_id) - require manual /do_it
    if _is_standalone(task):
        return "standalone (no capability_id)"

    # EXCLUDE: 'standalone' or 'exploratory' labels
    if _has_standalone_label(task):
        return "standalone/exploratory label"

    # EXCLUDE: tier=4 OR labels contain 'architecture' (architectural)
    if tier == 4:
        return "tier 4 (architecture)"
    if "architecture" in labels:
        return "architecture label"

    # EXCLUDE: files match security patterns
    if affected_files and _is_security_sensitive(affected_files):
        return "security-sensitive files"

    # EXCLUDE: task_type='research' OR title matches explore keywords
    if _is_exploratory(task):
        return "exploratory task"

    # EXCLUDE: affects 3+ domains (multi_domain)
    if affected_files and _count_domains(affected_files) >= 3:
        return "multi-domain (3+ areas)"

    return None  # No exclusion - task is eligible


@celery_app.task(name="summitflow.autonomous_work_pickup")  # type: ignore[misc]
def autonomous_work_pickup(project_id: str) -> dict[str, Any]:
    """Pick up and execute eligible tasks autonomously.

    Finds tasks that:
    - tier <= 3 (mechanical, not architectural)
    - status in (pending, paused, failed)
    - Pass all exclusion criteria

    Claims one task atomically and executes it via ImplementationExecutor.

    Args:
        project_id: Project to pick up work for

    Returns:
        Dict with execution results and exclusion stats
    """
    from app.services.implementation_executor import ImplementationExecutor
    from app.storage.agent_configs import is_autonomous_enabled

    try:
        # Check if autonomous execution is enabled
        if not is_autonomous_enabled(project_id):
            logger.debug(f"Autonomous execution disabled for {project_id}")
            return {"status": "disabled", "reason": "autonomous_enabled=false"}

        # Get ready tasks with tier <= 3
        ready_tasks = task_store.list_ready_tasks(project_id, limit=50)

        # Filter by tier and status
        eligible_tasks = [
            t
            for t in ready_tasks
            if (t.get("tier") or 2) <= 3 and t.get("status") in ("pending", "paused", "failed")
        ]

        if not eligible_tasks:
            return {"status": "no_work", "tasks_checked": len(ready_tasks)}

        # Apply exclusion criteria
        exclusion_stats: dict[str, int] = {}
        selected_task = None

        for task in eligible_tasks:
            exclusion_reason = _check_exclusion(task)
            if exclusion_reason:
                logger.debug(f"Excluded task {task['id']}: {exclusion_reason}")
                exclusion_stats[exclusion_reason] = exclusion_stats.get(exclusion_reason, 0) + 1
            else:
                selected_task = task
                break  # Take first eligible task

        if not selected_task:
            return {
                "status": "all_excluded",
                "tasks_checked": len(eligible_tasks),
                "exclusion_stats": exclusion_stats,
            }

        # Claim task atomically
        worker_id = f"autonomous-{project_id}"
        claimed = task_store.claim_task(selected_task["id"], worker_id, lock_duration_minutes=60)

        if not claimed:
            logger.info(f"Failed to claim task {selected_task['id']} - already claimed")
            return {"status": "claim_failed", "task_id": selected_task["id"]}

        logger.info(f"Claimed task {claimed['id']} for autonomous execution")

        # Execute via ImplementationExecutor with worktree isolation
        # TODO: Make use_worktree configurable via agent_configs when stabilized
        executor = ImplementationExecutor(project_id, use_worktree=True)

        try:
            session_id = executor.start_execution(claimed["id"], agent_type="gemini")
            result = executor.execute_next_task(session_id, max_iterations=5)

            if result.success:
                # Transition to pending_review for Opus gate
                task_store.update_task_status(claimed["id"], "pending_review")
                logger.info(f"Task {claimed['id']} succeeded, moved to pending_review")
                return {
                    "status": "success",
                    "task_id": claimed["id"],
                    "iterations": result.iterations,
                    "model_used": result.model_used,
                    "exclusion_stats": exclusion_stats,
                }
            else:
                # Mark failed with error message
                task_store.update_task_status(
                    claimed["id"],
                    "failed",
                    error_message=result.reason or result.error or "Unknown error",
                )
                task_store.release_task(claimed["id"])
                logger.warning(f"Task {claimed['id']} failed: {result.reason}")
                return {
                    "status": "execution_failed",
                    "task_id": claimed["id"],
                    "iterations": result.iterations,
                    "reason": result.reason,
                    "error": result.error,
                    "exclusion_stats": exclusion_stats,
                }

        except Exception as exec_error:
            # Release task on execution error
            task_store.release_task(claimed["id"])
            logger.error(f"Execution error for task {claimed['id']}: {exec_error}")
            return {
                "status": "execution_error",
                "task_id": claimed["id"],
                "error": str(exec_error),
                "exclusion_stats": exclusion_stats,
            }

    except Exception as e:
        logger.error(f"Error in autonomous_work_pickup: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(name="summitflow.review_pending_tasks")  # type: ignore[misc]
def review_pending_tasks(project_id: str) -> dict[str, Any]:
    """Review tasks in pending_review status via Opus.

    Fetches tasks awaiting review and runs Opus review on each.
    Applies the appropriate handler based on verdict.

    Args:
        project_id: Project to review tasks for

    Returns:
        Dict with reviewed_count, verdicts breakdown, and any errors
    """
    from app.services.autonomous.reviewer import (
        handle_approval,
        handle_fix_request,
        handle_rejection,
        opus_review,
    )
    from app.storage.agent_configs import is_autonomous_enabled

    try:
        # Check if autonomous execution is enabled
        if not is_autonomous_enabled(project_id):
            logger.debug(f"Autonomous execution disabled for {project_id}")
            return {"status": "disabled", "reason": "autonomous_enabled=false"}

        # Get tasks in pending_review status
        pending_tasks = task_store.list_tasks(
            project_id=project_id,
            status_filter="pending_review",
            limit=5,  # Review up to 5 at a time
        )

        if not pending_tasks:
            return {"status": "no_tasks", "reviewed_count": 0}

        verdicts: dict[str, int] = {"APPROVE": 0, "REJECT": 0, "REQUEST_FIX": 0}
        reviewed = 0
        errors: list[dict[str, str]] = []

        for task in pending_tasks:
            task_id = task["id"]
            try:
                # Run Opus review
                review_result = opus_review(task)
                verdict = review_result.get("verdict", "REQUEST_FIX")
                verdicts[verdict] = verdicts.get(verdict, 0) + 1
                reviewed += 1

                # Apply appropriate handler
                if verdict == "APPROVE":
                    handle_approval(task, review_result, auto_push=False)
                    logger.info(f"Task {task_id} approved by Opus review")
                elif verdict == "REJECT":
                    handle_rejection(task, review_result)
                    logger.info(f"Task {task_id} rejected by Opus review")
                else:  # REQUEST_FIX
                    handle_fix_request(task, review_result)
                    logger.info(f"Task {task_id} needs fixes per Opus review")

            except Exception as task_error:
                logger.error(f"Error reviewing task {task_id}: {task_error}")
                errors.append({"task_id": task_id, "error": str(task_error)})

        logger.info(
            f"Review complete for {project_id}: reviewed={reviewed}, "
            f"approved={verdicts['APPROVE']}, rejected={verdicts['REJECT']}, "
            f"fix_requested={verdicts['REQUEST_FIX']}"
        )

        return {
            "status": "success",
            "reviewed_count": reviewed,
            "verdicts": verdicts,
            "errors": errors if errors else None,
        }

    except Exception as e:
        logger.error(f"Error in review_pending_tasks: {e}")
        return {"status": "error", "error": str(e)}
