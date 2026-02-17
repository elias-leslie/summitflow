"""Utility functions for Quality Gate API."""

from typing import Any

from .quality_gate_models import CheckResultResponse


def result_to_response(result: dict[str, Any]) -> CheckResultResponse:
    """Convert storage result to API response.

    Args:
        result: Raw result dict from storage layer

    Returns:
        CheckResultResponse model
    """
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
