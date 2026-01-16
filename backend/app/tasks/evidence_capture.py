"""Celery tasks for scheduled evidence capture.

Tasks:
- daily_evidence_capture: Run evidence capture for a project
- capture_all_projects: Run evidence capture for all registered projects
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.evidence.capture_orchestrator import orchestrate_capture
from ..services.evidence.regression_detector import (
    RegressionResult,
    detect_regression_async,
    record_regression,
)
from ..storage import evidence_config, evidence_regressions
from ..storage.connection import get_connection
from ..storage.tasks.core import create_task

logger = get_logger(__name__)

# Rate limit delay between projects (seconds)
INTER_PROJECT_DELAY = 5


@shared_task(name="summitflow.daily_evidence_capture")  # type: ignore[untyped-decorator]
def daily_evidence_capture(
    project_id: str,
    scope: str = "project",
    entry_ids: list[int] | None = None,
    environment: str = "local",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Capture evidence for a project and run regression detection.

    Queries explorer_entries for capturable types (page, endpoint) and
    runs capture + regression detection for each entry.

    Args:
        project_id: Project to capture evidence for
        scope: 'project' (all entries), 'entry' (specific entries)
        entry_ids: Specific entry IDs to capture (when scope='entry')
        environment: Environment name (local, staging, production)
        dry_run: If True, only report what would be captured

    Returns:
        Summary dict with capture and regression stats
    """
    logger.info(
        "daily_evidence_capture_started",
        project_id=project_id,
        scope=scope,
        entry_ids=entry_ids,
        environment=environment,
        dry_run=dry_run,
    )

    try:
        # Get project config to check if evidence capture is enabled
        config = evidence_config.get_config(project_id)
        enabled_types = config.get("enabled_types", ["screenshot", "api_response"])

        if not enabled_types:
            logger.info(
                "evidence_capture_disabled",
                project_id=project_id,
                reason="no_enabled_types",
            )
            return {
                "status": "skipped",
                "project_id": project_id,
                "reason": "Evidence capture disabled for this project",
            }

        if dry_run:
            # Get count of entries that would be captured
            entries = _get_capturable_entries(project_id, scope, entry_ids)
            return {
                "status": "dry_run",
                "project_id": project_id,
                "entries_found": len(entries),
                "scope": scope,
            }

        # Run capture orchestration (async)
        capture_result = asyncio.run(
            orchestrate_capture(
                project_id=project_id,
                scope=scope,
                entry_ids=entry_ids,
                environment=environment,
            )
        )

        # Run regression detection on captured evidence
        regressions_found = 0
        if capture_result.captured > 0:
            regressions_found = asyncio.run(
                _run_regression_detection(project_id, capture_result.job_id)
            )
            capture_result.regressions_found = regressions_found

        # Update job with regression count
        _update_job_regressions(capture_result.job_id, regressions_found)

        logger.info(
            "daily_evidence_capture_complete",
            project_id=project_id,
            captured=capture_result.captured,
            failed=capture_result.failed,
            skipped=capture_result.skipped,
            regressions=regressions_found,
        )

        return {
            "status": "success",
            "project_id": project_id,
            "job_id": capture_result.job_id,
            "captured": capture_result.captured,
            "failed": capture_result.failed,
            "skipped": capture_result.skipped,
            "regressions_found": regressions_found,
            "errors": capture_result.errors[:5] if capture_result.errors else [],
        }

    except Exception as e:
        logger.error("daily_evidence_capture_failed", project_id=project_id, error=str(e))
        return {"status": "error", "project_id": project_id, "error": str(e)}


@shared_task(name="summitflow.capture_all_projects")  # type: ignore[untyped-decorator]
def capture_all_projects(
    environment: str = "local",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run evidence capture for all registered projects.

    Rate limited between projects to avoid overwhelming the system.

    Args:
        environment: Environment name (local, staging, production)
        dry_run: If True, only report what would be captured

    Returns:
        Summary dict with capture results per project
    """
    logger.info(
        "capture_all_projects_started",
        environment=environment,
        dry_run=dry_run,
    )

    try:
        # Get all projects with evidence capture enabled
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.project_id
                FROM projects p
                LEFT JOIN project_evidence_config pec ON p.project_id = pec.project_id
                WHERE pec.project_id IS NOT NULL
                   OR EXISTS (SELECT 1 FROM project_evidence_config)
                ORDER BY p.created_at
                """
            )
            projects = [row[0] for row in cur.fetchall()]

        if not projects:
            # Fall back to all projects if no config exists
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT project_id FROM projects ORDER BY created_at")
                projects = [row[0] for row in cur.fetchall()]

        captured = 0
        errors = 0
        details: list[dict[str, Any]] = []

        for i, proj_id in enumerate(projects):
            # Rate limit between projects (except first)
            if i > 0 and not dry_run:
                time.sleep(INTER_PROJECT_DELAY)

            if dry_run:
                entries = _get_capturable_entries(proj_id, "project", None)
                details.append(
                    {
                        "project_id": proj_id,
                        "status": "would_capture",
                        "entries_found": len(entries),
                    }
                )
                captured += 1
                continue

            try:
                result = daily_evidence_capture(
                    project_id=proj_id,
                    environment=environment,
                    dry_run=False,
                )
                details.append(result)
                if result.get("status") == "success":
                    captured += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                details.append(
                    {
                        "project_id": proj_id,
                        "status": "error",
                        "error": str(e),
                    }
                )
                logger.error(
                    "project_capture_failed",
                    project_id=proj_id,
                    error=str(e),
                )

        logger.info(
            "capture_all_projects_complete",
            captured=captured,
            errors=errors,
        )

        return {
            "status": "success" if errors == 0 else "partial",
            "dry_run": dry_run,
            "projects_captured": captured,
            "errors": errors,
            "details": details,
        }

    except Exception as e:
        logger.error("capture_all_projects_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def _get_capturable_entries(
    project_id: str,
    scope: str,
    entry_ids: list[int] | None,
) -> list[dict[str, Any]]:
    """Get explorer entries that can be captured."""
    with get_connection() as conn, conn.cursor() as cur:
        if scope == "entry" and entry_ids:
            cur.execute(
                """
                SELECT id, entry_type, path, name
                FROM explorer_entries
                WHERE project_id = %s AND id = ANY(%s)
                """,
                (project_id, entry_ids),
            )
        else:
            cur.execute(
                """
                SELECT id, entry_type, path, name
                FROM explorer_entries
                WHERE project_id = %s AND entry_type IN ('page', 'endpoint')
                ORDER BY entry_type, path
                """,
                (project_id,),
            )
        return [
            {
                "id": row[0],
                "entry_type": row[1],
                "path": row[2],
                "name": row[3],
            }
            for row in cur.fetchall()
        ]


async def _run_regression_detection(project_id: str, job_id: int) -> int:
    """Run regression detection for evidence captured in a job.

    Compares newly captured evidence against the most recent baseline
    for each explorer entry.

    Args:
        project_id: Project ID
        job_id: Capture job ID

    Returns:
        Number of regressions found
    """
    regressions_found = 0

    # Get evidence captured in this job
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.id, e.explorer_entry_id, e.evidence_type, e.file_path,
                   e.viewport_name, e.metadata
            FROM evidence e
            JOIN evidence_capture_jobs j ON e.project_id = j.project_id
            WHERE j.id = %s
              AND e.captured_at >= j.started_at
              AND e.captured_at <= COALESCE(j.completed_at, NOW())
            ORDER BY e.id
            """,
            (job_id,),
        )
        new_evidence = [
            {
                "id": row[0],
                "explorer_entry_id": row[1],
                "evidence_type": row[2],
                "file_path": row[3],
                "viewport_name": row[4],
                "metadata": row[5] or {},
            }
            for row in cur.fetchall()
        ]

    for evidence in new_evidence:
        # Find baseline (previous evidence for same entry + type + viewport)
        baseline = _get_baseline_evidence(
            project_id=project_id,
            explorer_entry_id=evidence["explorer_entry_id"],
            evidence_type=evidence["evidence_type"],
            viewport_name=evidence.get("viewport_name"),
            exclude_id=evidence["id"],
        )

        if baseline is None:
            # No baseline - first capture for this entry
            continue

        # Run regression detection
        result: RegressionResult = await detect_regression_async(
            project_id=project_id,
            evidence_id=evidence["id"],
            baseline_evidence_id=baseline["id"],
            current_data={
                "file_path": evidence["file_path"],
                "console": evidence["metadata"].get("console", []),
            },
            baseline_data={
                "file_path": baseline["file_path"],
                "console": baseline["metadata"].get("console", []),
            },
        )

        if result.has_regression:
            # Record the regression
            await record_regression(
                evidence_id=evidence["id"],
                baseline_evidence_id=baseline["id"],
                result=result,
            )
            regressions_found += 1

            logger.info(
                "regression_detected",
                project_id=project_id,
                evidence_id=evidence["id"],
                regression_type=result.regression_type,
                severity=result.severity,
            )

            # Check if this regression was previously resolved and reopen the task
            explorer_entry_id = evidence.get("explorer_entry_id")
            if explorer_entry_id and result.regression_type:
                resolved = evidence_regressions.get_resolved_for_entry(
                    project_id=project_id,
                    explorer_entry_id=explorer_entry_id,
                    regression_type=result.regression_type,
                )
                linked_task_id = resolved.get("linked_task_id") if resolved else None
                if linked_task_id:
                    reopened = _reopen_regression_task(
                        linked_task_id,
                        reason=f"Regression re-detected: {result.regression_type}",
                    )
                    if reopened:
                        logger.info(
                            "regression_task_reopened",
                            project_id=project_id,
                            task_id=linked_task_id,
                            regression_type=result.regression_type,
                        )

    return regressions_found


def _get_baseline_evidence(
    project_id: str,
    explorer_entry_id: int | None,
    evidence_type: str,
    viewport_name: str | None,
    exclude_id: int,
) -> dict[str, Any] | None:
    """Get the most recent baseline evidence for comparison."""
    if explorer_entry_id is None:
        return None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, file_path, metadata
            FROM evidence
            WHERE project_id = %s
              AND explorer_entry_id = %s
              AND evidence_type = %s
              AND (viewport_name = %s OR (%s IS NULL AND viewport_name IS NULL))
              AND id != %s
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (
                project_id,
                explorer_entry_id,
                evidence_type,
                viewport_name,
                viewport_name,
                exclude_id,
            ),
        )
        row = cur.fetchone()
        if row:
            return {
                "id": row[0],
                "file_path": row[1],
                "metadata": row[2] or {},
            }
    return None


def _update_job_regressions(job_id: int, regressions_found: int) -> None:
    """Update capture job with regression count."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evidence_capture_jobs
            SET regressions_found = %s
            WHERE id = %s
            """,
            (regressions_found, job_id),
        )
        conn.commit()


def create_regression_task(
    project_id: str,
    regression_id: int,
    entry_path: str,
    regression_type: str,
    severity: str,
    evidence_id: int,
    baseline_evidence_id: int | None,
) -> dict[str, Any] | None:
    """Create a bug task for a detected regression.

    When a regression is detected, this creates a SummitFlow task to fix it.
    The task is linked to the regression record for self-healing tracking.

    Args:
        project_id: Project ID
        regression_id: Regression record ID
        entry_path: Explorer entry path (e.g., /dashboard, /api/users)
        regression_type: Type of regression (visual, console, etc.)
        severity: Severity level (critical, high, medium, low)
        evidence_id: Current evidence ID showing the regression
        baseline_evidence_id: Baseline evidence ID for comparison

    Returns:
        Created task dict or None if creation failed
    """
    # Map severity to priority
    priority_map = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    priority = priority_map.get(severity, 2)

    # Build task title and description
    title = f"Fix: {regression_type.title()} regression on {entry_path}"

    description_parts = [
        f"**Regression Type:** {regression_type}",
        f"**Severity:** {severity}",
        f"**Entry Path:** {entry_path}",
        "",
        "## Evidence",
        f"- Current: evidence ID {evidence_id}",
    ]
    if baseline_evidence_id:
        description_parts.append(f"- Baseline: evidence ID {baseline_evidence_id}")

    description_parts.extend(
        [
            "",
            "## Investigation",
            "1. Compare baseline and current evidence screenshots",
            "2. Check console logs for new errors",
            "3. Review recent changes to the affected page/endpoint",
            "",
            "## Resolution",
            "Fix the regression and verify via new evidence capture.",
        ]
    )

    description = "\n".join(description_parts)

    try:
        task = create_task(
            project_id=project_id,
            title=title,
            description=description,
            task_type="bug",
            priority=priority,
        )

        # Link the task to the regression
        evidence_regressions.link_task(regression_id, task["id"])

        logger.info(
            "regression_task_created",
            project_id=project_id,
            task_id=task["id"],
            regression_id=regression_id,
            entry_path=entry_path,
        )

        return task

    except Exception as e:
        logger.error(
            "regression_task_creation_failed",
            project_id=project_id,
            regression_id=regression_id,
            error=str(e),
        )
        return None


@shared_task(name="summitflow.create_tasks_for_regressions")  # type: ignore[untyped-decorator]
def create_tasks_for_regressions(
    project_id: str,
    min_severity: str = "medium",
) -> dict[str, Any]:
    """Create bug tasks for unlinked regressions.

    Called after evidence capture to create tasks for detected regressions
    that don't already have linked tasks.

    Args:
        project_id: Project to process regressions for
        min_severity: Minimum severity to create tasks for (critical, high, medium, low)

    Returns:
        Summary dict with created task count
    """
    severity_levels = ["critical", "high", "medium", "low"]
    min_idx = severity_levels.index(min_severity) if min_severity in severity_levels else 2

    created = 0
    errors = 0

    # Get unreviewed regressions without linked tasks
    unreviewed = evidence_regressions.get_unreviewed(project_id)

    for regression in unreviewed:
        # Skip if already linked to a task
        if regression.get("linked_task_id"):
            continue

        # Skip if below minimum severity
        severity = regression.get("severity", "unknown")
        if severity not in severity_levels[: min_idx + 1]:
            continue

        # Get required fields - TypedDict has total=False so we access via get
        regression_id = regression.get("id")
        evidence_id = regression.get("evidence_id")
        if regression_id is None or evidence_id is None:
            continue

        # Get entry path for the regression
        entry_path = _get_entry_path_for_evidence(evidence_id)
        if not entry_path:
            entry_path = f"evidence-{evidence_id}"

        # Create the task
        task = create_regression_task(
            project_id=project_id,
            regression_id=regression_id,
            entry_path=entry_path,
            regression_type=regression.get("regression_type", "unknown"),
            severity=severity,
            evidence_id=evidence_id,
            baseline_evidence_id=regression.get("baseline_evidence_id"),
        )

        if task:
            created += 1
        else:
            errors += 1

    logger.info(
        "regression_tasks_created",
        project_id=project_id,
        created=created,
        errors=errors,
    )

    return {
        "status": "success" if errors == 0 else "partial",
        "project_id": project_id,
        "tasks_created": created,
        "errors": errors,
    }


def _get_entry_path_for_evidence(evidence_id: int) -> str | None:
    """Get the explorer entry path for an evidence record."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ee.path
            FROM evidence e
            JOIN explorer_entries ee ON e.explorer_entry_id = ee.id
            WHERE e.id = %s
            """,
            (evidence_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


@shared_task(name="summitflow.check_resolved_regressions")  # type: ignore[untyped-decorator]
def check_resolved_regressions(
    project_id: str,
    auto_close_tasks: bool = False,
) -> dict[str, Any]:
    """Check for regressions that have been resolved.

    When a new evidence capture shows no regression compared to baseline,
    but a previous capture for the same entry had a regression, mark
    the old regression as resolved.

    This implements the self-healing loop:
    1. Evidence capture detects regression -> creates task
    2. Developer fixes the issue
    3. Next capture shows no regression -> mark resolved, optionally close task

    Args:
        project_id: Project to check
        auto_close_tasks: If True, also close linked bug tasks

    Returns:
        Summary dict with resolved count
    """
    resolved = 0
    tasks_closed = 0

    # Get all detected (unresolved) regressions for this project
    detected = evidence_regressions.get_unreviewed(project_id, limit=100)

    for regression in detected:
        regression_id = regression.get("id")
        evidence_id = regression.get("evidence_id")
        if regression_id is None or evidence_id is None:
            continue

        # Check if a newer evidence exists for the same entry without regression
        if _regression_appears_resolved(evidence_id):
            # Mark regression as resolved
            evidence_regressions.update_status(regression_id, "resolved")
            resolved += 1

            logger.info(
                "regression_resolved",
                project_id=project_id,
                regression_id=regression_id,
            )

            # Optionally close the linked task
            linked_task_id = regression.get("linked_task_id")
            if auto_close_tasks and linked_task_id:
                task_closed = _close_regression_task(linked_task_id)
                if task_closed:
                    tasks_closed += 1

    logger.info(
        "check_resolved_regressions_complete",
        project_id=project_id,
        resolved=resolved,
        tasks_closed=tasks_closed,
    )

    return {
        "status": "success",
        "project_id": project_id,
        "regressions_resolved": resolved,
        "tasks_closed": tasks_closed,
    }


def _regression_appears_resolved(evidence_id: int) -> bool:
    """Check if a regression appears to be resolved.

    A regression is considered resolved if:
    1. A newer evidence exists for the same explorer entry
    2. The newer evidence has no associated regression record

    Args:
        evidence_id: Evidence ID that had the regression

    Returns:
        True if regression appears resolved
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get the entry and capture time for this evidence
        cur.execute(
            """
            SELECT explorer_entry_id, evidence_type, viewport_name, captured_at
            FROM evidence
            WHERE id = %s
            """,
            (evidence_id,),
        )
        row = cur.fetchone()
        if not row:
            return False

        entry_id, ev_type, viewport, captured_at = row

        if entry_id is None:
            return False

        # Check if newer evidence exists without a regression
        cur.execute(
            """
            SELECT e.id
            FROM evidence e
            LEFT JOIN evidence_regressions er ON e.id = er.evidence_id
            WHERE e.explorer_entry_id = %s
              AND e.evidence_type = %s
              AND (e.viewport_name = %s OR (%s IS NULL AND e.viewport_name IS NULL))
              AND e.captured_at > %s
              AND er.id IS NULL  -- No regression record
            ORDER BY e.captured_at DESC
            LIMIT 1
            """,
            (entry_id, ev_type, viewport, viewport, captured_at),
        )
        return cur.fetchone() is not None


def _close_regression_task(task_id: str) -> bool:
    """Close a regression bug task.

    Args:
        task_id: Task ID to close

    Returns:
        True if task was closed
    """
    from ..storage.tasks.core import get_task, update_task

    try:
        task = get_task(task_id)
        if not task:
            return False

        # Only close if still pending or running
        if task.get("status") not in ("pending", "running", "paused"):
            return False

        update_task(
            task_id,
            status="completed",
            progress_log="Auto-closed: Regression resolved in evidence capture",
        )

        logger.info("regression_task_closed", task_id=task_id)
        return True

    except Exception as e:
        logger.error("regression_task_close_failed", task_id=task_id, error=str(e))
        return False


def _reopen_regression_task(task_id: str, reason: str) -> bool:
    """Reopen a previously closed regression task.

    Called when a regression is re-detected after being marked as resolved.

    Args:
        task_id: Task ID to reopen
        reason: Reason for reopening (added to progress log)

    Returns:
        True if task was reopened
    """
    from ..storage.tasks.core import get_task, update_task

    try:
        task = get_task(task_id)
        if not task:
            return False

        # Only reopen if it was completed (closed by auto-close)
        if task.get("status") != "completed":
            return False

        update_task(
            task_id,
            status="pending",
            progress_log=f"Auto-reopened: {reason}",
        )

        logger.info("regression_task_reopened", task_id=task_id, reason=reason)
        return True

    except Exception as e:
        logger.error("regression_task_reopen_failed", task_id=task_id, error=str(e))
        return False
