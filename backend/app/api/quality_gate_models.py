"""Data models for Quality Gate API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

QualityCheckType = Literal["pytest", "vitest", "ruff", "types", "biome", "tsc"]
FixableQualityCheckType = Literal["pytest", "ruff", "types", "biome", "tsc"]


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

    check_type: QualityCheckType
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

    check_type: QualityCheckType
    status: Literal["pass", "fail", "error", "skipped"]
    error_count: int = 0
    warning_count: int = 0
    errors: list[dict[str, Any]] | None = None  # List of {message, file, line, column}
    run_duration_ms: int | None = None
    git_sha: str | None = None
    triggered_by: Literal["commit", "manual", "ci", "agent"] = "commit"


class SyncResultsResponse(BaseModel):
    """Response from syncing quality check results."""

    synced: bool
    check_type: str
    status: str
    created_count: int
    auto_closed_count: int


class AutoFixRequest(BaseModel):
    """Request to trigger auto-fix."""

    check_type: FixableQualityCheckType | None = None
    limit: int = 10


class AutoFixResponse(BaseModel):
    """Response from auto-fix operation."""

    triggered: bool
    check_type: str | None
    fixed: int
    failed: int
    escalated: int
    message: str


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
