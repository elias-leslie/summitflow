"""Quality Gate API - REST endpoints for quality check management.

Provides endpoints for:
- GET /projects/{project_id}/quality/health - Get quality gate health summary
- GET /projects/{project_id}/quality/results - List check results
- POST /projects/{project_id}/quality/results - Record a check result
- POST /projects/{project_id}/quality/sync - Sync results from dt output
- POST /projects/{project_id}/errors/console - Capture frontend console errors
"""

import hashlib
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..logging_config import get_logger
from ..storage import quality_check_results as qcr_store
from ..storage.connection import get_connection
from ..storage.tasks.core import create_task, update_task
from ..storage.tasks.dedup import bug_task_exists_for_error

logger = get_logger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class CheckResultResponse(BaseModel):
    """Response model for a quality check result."""

    id: int
    project_id: str
    check_type: str
    check_name: str | None
    status: str
    error_count: int
    warning_count: int
    error_message: str | None
    file_path: str | None
    line_number: int | None
    column_number: int | None
    run_duration_ms: int | None
    git_sha: str | None
    triggered_by: str | None
    fix_attempted: bool
    fix_attempts: int
    fixed_at: datetime | None
    fixed_by: str | None
    created_at: datetime
    updated_at: datetime
    escalation_task_id: str | None = None


class CheckResultListResponse(BaseModel):
    """Response for listing check results."""

    items: list[CheckResultResponse]
    total: int
    unfixed_count: int


class HealthSummaryResponse(BaseModel):
    """Response for quality gate health summary."""

    project_id: str
    overall_pass: bool
    total_unfixed: int
    checks: dict[str, dict[str, Any]]


class CreateCheckResultRequest(BaseModel):
    """Request to create a check result."""

    check_type: Literal["pytest", "ruff", "mypy", "biome", "tsc"]
    status: Literal["pass", "fail", "error", "skipped"]
    check_name: str | None = None
    error_count: int = 0
    warning_count: int = 0
    error_message: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    column_number: int | None = None
    run_duration_ms: int | None = None
    git_sha: str | None = None
    triggered_by: Literal["commit", "manual", "ci", "agent"] | None = None


class SyncResultsRequest(BaseModel):
    """Request to sync results from dt output."""

    check_type: Literal["pytest", "ruff", "mypy", "biome", "tsc"]
    status: Literal["pass", "fail", "error", "skipped"]
    error_count: int = 0
    warning_count: int = 0
    errors: list[dict[str, Any]] | None = None  # List of {message, file, line, column}
    run_duration_ms: int | None = None
    git_sha: str | None = None
    triggered_by: Literal["commit", "manual", "ci", "agent"] = "commit"


# ============================================================================
# Helpers
# ============================================================================


def _validate_project_exists(project_id: str) -> None:
    """Validate project exists in database."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


def _result_to_response(result: dict[str, Any]) -> CheckResultResponse:
    """Convert storage result to API response."""
    return CheckResultResponse(
        id=result["id"],
        project_id=result["project_id"],
        check_type=result["check_type"],
        check_name=result["check_name"],
        status=result["status"],
        error_count=result["error_count"],
        warning_count=result["warning_count"],
        error_message=result["error_message"],
        file_path=result["file_path"],
        line_number=result["line_number"],
        column_number=result["column_number"],
        run_duration_ms=result["run_duration_ms"],
        git_sha=result["git_sha"],
        triggered_by=result["triggered_by"],
        fix_attempted=result["fix_attempted"],
        fix_attempts=result["fix_attempts"],
        fixed_at=result["fixed_at"],
        fixed_by=result["fixed_by"],
        created_at=result["created_at"],
        updated_at=result["updated_at"],
        escalation_task_id=result.get("escalation_task_id"),
    )


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/projects/{project_id}/quality/health")
async def get_health_summary(project_id: str) -> HealthSummaryResponse:
    """Get quality gate health summary for a project.

    Returns the latest status for each check type and overall pass/fail.
    """
    _validate_project_exists(project_id)

    with get_connection() as conn:
        summary = qcr_store.get_project_health_summary(conn, project_id)

    return HealthSummaryResponse(
        project_id=summary["project_id"],
        overall_pass=summary["overall_pass"],
        total_unfixed=summary["total_unfixed"],
        checks=summary["checks"],
    )


@router.get("/projects/{project_id}/quality/results")
async def list_check_results(
    project_id: str,
    check_type: Literal["pytest", "ruff", "mypy", "biome", "tsc"] | None = None,
    status: Literal["pass", "fail", "error", "skipped"] | None = None,
    unfixed_only: bool = False,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> CheckResultListResponse:
    """List quality check results for a project.

    Supports filtering by check type, status, and unfixed failures.
    """
    _validate_project_exists(project_id)

    with get_connection() as conn:
        results = qcr_store.list_check_results(
            conn,
            project_id,
            check_type=check_type,
            status=status,
            unfixed_only=unfixed_only,
            limit=limit,
            offset=offset,
        )
        unfixed_count = qcr_store.get_unfixed_count(conn, project_id, check_type)

    return CheckResultListResponse(
        items=[_result_to_response(r) for r in results],
        total=len(results),
        unfixed_count=unfixed_count,
    )


@router.post("/projects/{project_id}/quality/results")
async def create_check_result(
    project_id: str,
    request: CreateCheckResultRequest,
) -> CheckResultResponse:
    """Record a quality check result."""
    _validate_project_exists(project_id)

    with get_connection() as conn:
        result = qcr_store.create_check_result(
            conn,
            project_id,
            request.check_type,
            request.status,
            check_name=request.check_name,
            error_count=request.error_count,
            warning_count=request.warning_count,
            error_message=request.error_message,
            file_path=request.file_path,
            line_number=request.line_number,
            column_number=request.column_number,
            run_duration_ms=request.run_duration_ms,
            git_sha=request.git_sha,
            triggered_by=request.triggered_by,
        )
        conn.commit()

    return _result_to_response(result)


@router.post("/projects/{project_id}/quality/sync")
async def sync_results(
    project_id: str,
    request: SyncResultsRequest,
) -> dict[str, Any]:
    """Sync quality check results from dt output.

    Creates individual result records for each error in the errors list,
    or a single pass record if no errors.
    """
    _validate_project_exists(project_id)

    created_count = 0

    auto_closed_count = 0

    with get_connection() as conn:
        if request.status == "pass" or not request.errors:
            # Single pass/error record
            qcr_store.create_check_result(
                conn,
                project_id,
                request.check_type,
                request.status,
                error_count=request.error_count,
                warning_count=request.warning_count,
                run_duration_ms=request.run_duration_ms,
                git_sha=request.git_sha,
                triggered_by=request.triggered_by,
            )
            created_count = 1

            # Auto-close any unfixed errors for this check type
            if request.status == "pass":
                auto_closed_count, task_ids = qcr_store.auto_close_resolved(
                    conn, project_id, request.check_type
                )
                # Close any linked escalation tasks
                for task_id in task_ids:
                    update_task(task_id, status="completed")
        else:
            # Create record for each error
            for error in request.errors:
                qcr_store.create_check_result(
                    conn,
                    project_id,
                    request.check_type,
                    "fail",
                    check_name=error.get("rule") or error.get("test_name"),
                    error_count=1,
                    error_message=error.get("message"),
                    file_path=error.get("file"),
                    line_number=error.get("line"),
                    column_number=error.get("column"),
                    run_duration_ms=request.run_duration_ms,
                    git_sha=request.git_sha,
                    triggered_by=request.triggered_by,
                )
                created_count += 1

        conn.commit()

    return {
        "synced": True,
        "check_type": request.check_type,
        "status": request.status,
        "created_count": created_count,
        "auto_closed_count": auto_closed_count,
    }


@router.post("/projects/{project_id}/quality/results/{result_id}/fix-attempt")
async def record_fix_attempt(
    project_id: str,
    result_id: int,
) -> CheckResultResponse:
    """Record a fix attempt for a check result."""
    _validate_project_exists(project_id)

    with get_connection() as conn:
        # Verify result belongs to project
        result = qcr_store.get_check_result(conn, result_id)
        if not result or result["project_id"] != project_id:
            raise HTTPException(
                status_code=404,
                detail=f"Check result {result_id} not found in project {project_id}",
            )

        updated = qcr_store.record_fix_attempt(conn, result_id)
        conn.commit()

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to record fix attempt")

    return _result_to_response(updated)


@router.post("/projects/{project_id}/quality/results/{result_id}/mark-fixed")
async def mark_result_fixed(
    project_id: str,
    result_id: int,
    fixed_by: str = Query(description="Who/what fixed it (e.g., 'gemini-flash', 'user')"),
) -> CheckResultResponse:
    """Mark a check result as fixed."""
    _validate_project_exists(project_id)

    with get_connection() as conn:
        # Verify result belongs to project
        result = qcr_store.get_check_result(conn, result_id)
        if not result or result["project_id"] != project_id:
            raise HTTPException(
                status_code=404,
                detail=f"Check result {result_id} not found in project {project_id}",
            )

        updated = qcr_store.mark_fixed(conn, result_id, fixed_by)
        conn.commit()

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to mark result as fixed")

    return _result_to_response(updated)


# ============================================================================
# Auto-Fix Endpoints
# ============================================================================


class AutoFixRequest(BaseModel):
    """Request to trigger auto-fix."""

    check_type: Literal["pytest", "ruff", "mypy", "biome", "tsc"] | None = None
    limit: int = 10


class AutoFixResponse(BaseModel):
    """Response from auto-fix operation."""

    triggered: bool
    check_type: str | None
    fixed: int
    failed: int
    escalated: int
    message: str


@router.post("/projects/{project_id}/quality/auto-fix")
async def trigger_auto_fix(
    project_id: str,
    request: AutoFixRequest,
) -> AutoFixResponse:
    """Trigger auto-fix for unfixed quality issues.

    Uses GEMINI_FLASH for lint/type errors (ruff, mypy, biome, tsc)
    and CLAUDE_SONNET for test failures (pytest).

    Args:
        project_id: Project ID
        request: Auto-fix configuration

    Returns:
        AutoFixResponse with fix counts
    """
    _validate_project_exists(project_id)

    from ..services.quality_gate import fix_unfixed_errors
    from ..services.quality_gate.test_fix_agent import fix_failing_tests

    with get_connection() as conn:
        results = {"fixed": 0, "failed": 0, "escalated": 0}

        if request.check_type == "pytest":
            # Use test-specific fix agent
            test_results = fix_failing_tests(conn, project_id, limit=request.limit)
            results["fixed"] = test_results["fixed"]
            results["failed"] = test_results["failed"]
            results["escalated"] = test_results["escalated"]
        elif request.check_type in ("ruff", "mypy", "biome", "tsc"):
            # Use lint/type fix agent
            lint_results = fix_unfixed_errors(
                conn, project_id, check_type=request.check_type, limit=request.limit
            )
            results["fixed"] = lint_results["fixed"]
            results["failed"] = lint_results["failed"]
            results["escalated"] = lint_results["escalated"]
        else:
            # Fix all types
            lint_results = fix_unfixed_errors(conn, project_id, limit=request.limit)
            results["fixed"] += lint_results["fixed"]
            results["failed"] += lint_results["failed"]
            results["escalated"] += lint_results["escalated"]

            test_results = fix_failing_tests(conn, project_id, limit=request.limit)
            results["fixed"] += test_results["fixed"]
            results["failed"] += test_results["failed"]
            results["escalated"] += test_results["escalated"]

        conn.commit()

    total_attempts = results["fixed"] + results["failed"] + results["escalated"]
    if total_attempts == 0:
        message = "No unfixed issues to process"
    elif results["escalated"] > 0:
        message = f"Fixed {results['fixed']}, {results['escalated']} escalated for human review"
    elif results["failed"] > 0:
        message = f"Fixed {results['fixed']}, {results['failed']} still failing"
    else:
        message = f"All {results['fixed']} issues fixed"

    return AutoFixResponse(
        triggered=total_attempts > 0,
        check_type=request.check_type,
        **results,
        message=message,
    )


# ============================================================================
# Console Error Capture Endpoints
# ============================================================================


class ConsoleErrorRequest(BaseModel):
    """Request to capture a frontend console error."""

    error: str
    stack: str | None = None
    url: str
    timestamp: str
    user_agent: str | None = None


class ConsoleErrorResponse(BaseModel):
    """Response from console error capture."""

    success: bool
    task_id: str | None = None
    message: str
    is_duplicate: bool = False


def _compute_console_error_hash(error: str, stack: str | None) -> str:
    """Compute a stable hash for a console error.

    Args:
        error: Error message
        stack: Stack trace (optional)

    Returns:
        16-character hash
    """
    content = f"{error}|{stack or ''}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


@router.post("/projects/{project_id}/errors/console")
async def capture_console_error(
    project_id: str,
    request: ConsoleErrorRequest,
) -> ConsoleErrorResponse:
    """Capture a frontend console error and create a bug task.

    This endpoint is called by frontend error handlers to report
    JavaScript errors for investigation.

    Deduplication: Won't create duplicate tasks for same error+stack
    within the last 24 hours.

    Args:
        project_id: Project ID
        request: Error details from frontend

    Returns:
        ConsoleErrorResponse with task info if created
    """
    _validate_project_exists(project_id)

    # Build title from error message (truncate for readability)
    error_preview = request.error[:80]
    if len(request.error) > 80:
        error_preview += "..."
    title = f"Fix: [Frontend] {error_preview}"

    # Check for duplicate
    if bug_task_exists_for_error(project_id, title):
        logger.info(
            "skipping_duplicate_console_error",
            project_id=project_id,
            error=request.error[:50],
        )
        return ConsoleErrorResponse(
            success=True,
            message="Duplicate error - task already exists",
            is_duplicate=True,
        )

    # Build description with full context
    error_hash = _compute_console_error_hash(request.error, request.stack)
    description_parts = [
        f"**Captured:** {request.timestamp}",
        f"**URL:** {request.url}",
    ]
    if request.user_agent:
        description_parts.append(f"**User Agent:** {request.user_agent}")
    description_parts.extend(
        [
            "",
            "**Error:**",
            "```",
            request.error,
            "```",
        ]
    )
    if request.stack:
        description_parts.extend(
            [
                "",
                "**Stack Trace:**",
                "```",
                request.stack[:2000],  # Limit stack trace size
                "```",
            ]
        )
    description_parts.extend(
        [
            "",
            f"**Error Hash:** {error_hash}",
            "",
            "This bug was auto-created from frontend console error capture.",
        ]
    )
    description = "\n".join(description_parts)

    task = create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=2,
        task_type="bug",
        complexity="STANDARD",
        autonomous=True,
    )

    logger.info(
        "created_console_error_task",
        task_id=task["id"],
        project_id=project_id,
        error_hash=error_hash,
    )

    return ConsoleErrorResponse(
        success=True,
        task_id=task["id"],
        message="Bug task created for console error",
    )
