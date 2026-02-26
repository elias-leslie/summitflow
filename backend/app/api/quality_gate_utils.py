"""Utility functions for Quality Gate API."""

from typing import Any

import psycopg
from fastapi import HTTPException

from ..storage import quality_check_results as qcr_store
from ..storage.tasks.core import update_task
from .quality_gate_models import CheckResultResponse, SyncResultsRequest


def result_to_response(result: dict[str, Any]) -> CheckResultResponse:
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


def verify_result(
    conn: psycopg.Connection[Any], result_id: int, project_id: str
) -> dict[str, Any]:
    """Verify a result exists and belongs to the project, raising 404 if not."""
    result = qcr_store.get_check_result(conn, result_id)
    if not result or result["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Check result {result_id} not found in project {project_id}",
        )
    return result


def sync_pass_record(
    conn: psycopg.Connection[Any], project_id: str, request: SyncResultsRequest
) -> int:
    """Create a single pass/error record and auto-close resolved errors. Returns auto_closed_count."""
    qcr_store.create_check_result(
        conn, project_id, request.check_type, request.status,
        error_count=request.error_count, warning_count=request.warning_count,
        run_duration_ms=request.run_duration_ms, git_sha=request.git_sha,
        triggered_by=request.triggered_by,
    )
    if request.status != "pass":
        return 0
    auto_closed_count, task_ids = qcr_store.auto_close_resolved(conn, project_id, request.check_type)
    for task_id in task_ids:
        update_task(task_id, status="completed")
    return auto_closed_count


def sync_error_records(
    conn: psycopg.Connection[Any], project_id: str, request: SyncResultsRequest
) -> int:
    """Create one result record per error. Returns count of created records."""
    errors = request.errors or []
    for error in errors:
        qcr_store.create_check_result(
            conn, project_id, request.check_type, "fail",
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
    return len(errors)
