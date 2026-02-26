"""Quality Gate API - REST endpoints for quality check management."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ..storage import quality_check_results as qcr_store
from ..storage.connection import get_connection
from .dependencies import validate_project_exists
from .quality_gate_models import (
    CheckResultListResponse,
    CheckResultResponse,
    CreateCheckResultRequest,
    HealthSummaryResponse,
    SyncResultsRequest,
    SyncResultsResponse,
)
from .quality_gate_utils import (
    result_to_response,
    sync_error_records,
    sync_pass_record,
    verify_result,
)

router = APIRouter()


@router.get("/projects/{project_id}/quality/health")
async def get_health_summary(project_id: str) -> HealthSummaryResponse:
    """Get quality gate health summary for a project."""
    validate_project_exists(project_id)
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
    check_type: Literal["pytest", "ruff", "types", "biome", "tsc"] | None = None,
    status: Literal["pass", "fail", "error", "skipped"] | None = None,
    unfixed_only: bool = False,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> CheckResultListResponse:
    """List quality check results for a project."""
    validate_project_exists(project_id)
    with get_connection() as conn:
        results = qcr_store.list_check_results(
            conn, project_id, check_type=check_type, status=status,
            unfixed_only=unfixed_only, limit=limit, offset=offset,
        )
        unfixed_count = qcr_store.get_unfixed_count(conn, project_id, check_type)
    return CheckResultListResponse(
        items=[result_to_response(r) for r in results],
        total=len(results),
        unfixed_count=unfixed_count,
    )


@router.post("/projects/{project_id}/quality/results")
async def create_check_result(
    project_id: str,
    request: CreateCheckResultRequest,
) -> CheckResultResponse:
    """Record a quality check result."""
    validate_project_exists(project_id)
    with get_connection() as conn:
        result = qcr_store.create_check_result(
            conn, project_id, request.check_type, request.status,
            check_name=request.check_name, error_count=request.error_count,
            warning_count=request.warning_count, error_message=request.error_message,
            file_path=request.file_path, line_number=request.line_number,
            column_number=request.column_number, run_duration_ms=request.run_duration_ms,
            git_sha=request.git_sha, triggered_by=request.triggered_by,
        )
        conn.commit()
    return result_to_response(result)


@router.post("/projects/{project_id}/quality/sync")
async def sync_results(
    project_id: str,
    request: SyncResultsRequest,
) -> SyncResultsResponse:
    """Sync quality check results from dt output."""
    validate_project_exists(project_id)
    with get_connection() as conn:
        if request.status == "pass" or not request.errors:
            auto_closed = sync_pass_record(conn, project_id, request)
            created_count = 1
        else:
            created_count = sync_error_records(conn, project_id, request)
            auto_closed = 0
        conn.commit()
    return SyncResultsResponse(
        synced=True,
        check_type=request.check_type,
        status=request.status,
        created_count=created_count,
        auto_closed_count=auto_closed,
    )


@router.post("/projects/{project_id}/quality/results/{result_id}/fix-attempt")
async def record_fix_attempt(project_id: str, result_id: int) -> CheckResultResponse:
    """Record a fix attempt for a check result."""
    validate_project_exists(project_id)
    with get_connection() as conn:
        verify_result(conn, result_id, project_id)
        updated = qcr_store.record_fix_attempt(conn, result_id)
        conn.commit()
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to record fix attempt")
    return result_to_response(updated)


@router.post("/projects/{project_id}/quality/results/{result_id}/mark-fixed")
async def mark_result_fixed(
    project_id: str,
    result_id: int,
    fixed_by: str = Query(description="Who/what fixed it (e.g., 'gemini-flash', 'user')"),
) -> CheckResultResponse:
    """Mark a check result as fixed."""
    validate_project_exists(project_id)
    with get_connection() as conn:
        verify_result(conn, result_id, project_id)
        updated = qcr_store.mark_fixed(conn, result_id, fixed_by)
        conn.commit()
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to mark result as fixed")
    return result_to_response(updated)
