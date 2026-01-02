"""Autonomous task execution Celery tasks.

This module provides Celery tasks for autonomous code execution:
- reset_expired_task_claims: Clean up stale task locks
- generate_tasks_from_scan: Create tasks from Explorer refactor targets
- generate_bug_tasks: DISABLED - was too noisy (environmental/transient errors)
- autonomous_work_pickup: Pick up and execute eligible tasks
- review_pending_tasks: Opus review gate for pending_review tasks
- cleanup_orphaned_worktrees: Clean up stale worktrees
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.celery_app import celery_app
from app.services.task_issue_mapper import link_issue_to_task
from app.services.worktree_manager import get_worktree_manager
from app.storage import qa_issues as qa_storage
from app.storage import tasks as task_store
from app.storage.explorer_analysis import get_refactor_targets
from app.storage.steps import bulk_create_steps
from app.storage.subtasks import bulk_create_subtasks

logger = logging.getLogger(__name__)

# Default repo path for worktree cleanup
DEFAULT_REPO_PATH = Path("/home/kasadis/summitflow")

# Validation mode flags - disabled after phase 5 validation
# Re-enable for debugging or controlled testing
AUTONOMOUS_DRY_RUN = False  # When True, log what would execute but don't actually run
VALIDATION_MODE = False  # When True, only execute tasks in ALLOWED_TASK_IDS
ALLOWED_TASK_IDS: list[str] = []  # Empty = no filter (when VALIDATION_MODE=True)

# Patterns in error titles that should NOT generate bug tasks
# These are environmental/transient issues, not actual code bugs
ERROR_BLOCKLIST_PATTERNS = [
    # Database connection issues (environmental, not bugs)
    "postgresql",
    "role.*does not exist",
    "database.*role",
    "authentication failure",
    "connection failed",
    "psql",
    # Pre-existing type errors (not new bugs, need consolidated approach)
    "mypy",
    "type error",
    "type mismatch",
    "type check",
    # TypeScript transient issues
    "typescript.*not found",
    "ts2307",
    "ts6053",
    "tsc",
    "module resolution",
    # Missing tools/dependencies (environmental)
    "missing from path",
    "cli missing",
    "command not found",
    "dependency",
    "package.json",
    # Transient test/build failures
    "file not found",
    "test file",
    "migration inspection",
    "jq filter",
    "jq syntax",
    # Capability/worktree verification (test infrastructure)
    "capability verification",
    "worktree.*verification",
]


def _is_blocklisted_error(title: str) -> bool:
    """Check if error title matches blocklist patterns.

    These are environmental/transient issues that should NOT create tasks.
    """
    title_lower = title.lower()
    return any(re.search(pattern, title_lower) for pattern in ERROR_BLOCKLIST_PATTERNS)


@celery_app.task(name="summitflow.reset_expired_task_claims")  # type: ignore[untyped-decorator]
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
            if _is_blocklisted_error(error_title):
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

    Exception: auto-generated tasks from Explorer scans have subtasks+steps
    which can be verified without capability linkage.
    """
    labels = task.get("labels") or []
    if "auto-generated" in labels:
        return False  # Auto-generated tasks have subtask verification
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


@celery_app.task(name="summitflow.autonomous_work_pickup")  # type: ignore[untyped-decorator]
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

        # In validation mode, fetch allowed tasks directly (bypass limit)
        if VALIDATION_MODE and ALLOWED_TASK_IDS:
            eligible_tasks = []
            for task_id in ALLOWED_TASK_IDS:
                task = task_store.get_task(task_id)
                if task and task.get("status") in ("pending", "paused", "failed"):
                    tier = task.get("tier") or 2
                    if tier <= 3:
                        eligible_tasks.append(task)
            if not eligible_tasks:
                return {
                    "status": "no_allowed_tasks_ready",
                    "allowed_ids": ALLOWED_TASK_IDS,
                }
        else:
            # Normal mode: Get ready tasks with tier <= 3
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

        # Dry-run mode: log what would execute but don't actually run
        if AUTONOMOUS_DRY_RUN:
            logger.info(
                f"DRY_RUN: Would execute {selected_task['id']}: {selected_task['title'][:60]}"
            )
            return {
                "status": "dry_run",
                "task_id": selected_task["id"],
                "title": selected_task["title"],
                "exclusion_stats": exclusion_stats,
            }

        # Validation mode: only execute tasks in allowlist
        if VALIDATION_MODE and selected_task["id"] not in ALLOWED_TASK_IDS:
            logger.info(f"VALIDATION: Skipping {selected_task['id']} (not in allowlist)")
            return {
                "status": "validation_skip",
                "task_id": selected_task["id"],
                "title": selected_task["title"],
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

                # Cleanup worktree on failure
                try:
                    worktree_manager = get_worktree_manager(DEFAULT_REPO_PATH)
                    worktree_manager.remove_worktree(project_id, claimed["id"])
                    logger.info(f"Cleaned up worktree for failed task {claimed['id']}")
                except Exception as cleanup_err:
                    logger.warning(f"Worktree cleanup failed: {cleanup_err}")

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

            # Cleanup worktree on error
            try:
                worktree_manager = get_worktree_manager(DEFAULT_REPO_PATH)
                worktree_manager.remove_worktree(project_id, claimed["id"])
                logger.info(f"Cleaned up worktree for errored task {claimed['id']}")
            except Exception as cleanup_err:
                logger.warning(f"Worktree cleanup failed: {cleanup_err}")

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


@celery_app.task(name="summitflow.review_pending_tasks")  # type: ignore[untyped-decorator]
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


@celery_app.task(name="summitflow.cleanup_orphaned_worktrees")  # type: ignore[untyped-decorator]
def cleanup_orphaned_worktrees(max_age_hours: int = 24) -> dict[str, Any]:
    """Clean up orphaned worktrees that are older than max_age_hours.

    This task runs periodically to remove worktrees that:
    - Are older than max_age_hours (abandoned from crashed executions)
    - Belong to tasks no longer in 'running' status

    Args:
        max_age_hours: Maximum age in hours before cleanup (default 24)

    Returns:
        Dict with removed_count and any errors
    """
    try:
        worktree_manager = get_worktree_manager(DEFAULT_REPO_PATH)

        # First, cleanup by age
        removed_by_age = worktree_manager.cleanup_stale_worktrees(max_age_hours)
        logger.info(f"Cleaned up {removed_by_age} stale worktrees by age")

        # Second, cleanup worktrees for tasks no longer running
        removed_by_status = 0
        active_worktrees = worktree_manager.list_active_worktrees()

        for worktree in active_worktrees:
            task_id = worktree.task_id
            task = task_store.get_task(task_id)

            # Remove if task doesn't exist or is not in running/pending_review
            reason = ""
            if not task:
                reason = "task not found"
            elif task.get("status") not in ("running", "pending_review"):
                reason = f"task status is {task.get('status')}"

            if reason:  # reason being set means we should remove
                try:
                    worktree_manager.remove_worktree(worktree.project_id, task_id)
                    removed_by_status += 1
                    logger.info(f"Cleaned up worktree for {task_id}: {reason}")
                except Exception as e:
                    logger.warning(f"Failed to remove worktree for {task_id}: {e}")

        total_removed = removed_by_age + removed_by_status
        logger.info(
            f"Worktree cleanup complete: {total_removed} removed "
            f"(by_age={removed_by_age}, by_status={removed_by_status})"
        )

        return {
            "status": "success",
            "removed_count": total_removed,
            "removed_by_age": removed_by_age,
            "removed_by_status": removed_by_status,
        }

    except Exception as e:
        logger.error(f"Error in cleanup_orphaned_worktrees: {e}")
        return {"status": "error", "error": str(e), "removed_count": 0}
