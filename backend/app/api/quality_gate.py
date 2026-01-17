"""Quality Gate API - REST endpoints for quality check management.

Provides endpoints for:
- GET /projects/{project_id}/quality/health - Get quality gate health summary
- GET /projects/{project_id}/quality/results - List check results
- POST /projects/{project_id}/quality/results - Record a check result
- POST /projects/{project_id}/quality/sync - Sync results from dt output
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..storage import quality_check_results as qcr_store
from ..storage.connection import get_connection

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
