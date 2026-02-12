"""Pydantic models for backup API requests and responses."""

from datetime import datetime

from pydantic import BaseModel


class BackupCreate(BaseModel):
    """Request model for creating a backup."""

    note: str | None = None
    keep_local: bool = False


class BackupResponse(BaseModel):
    """Response model for a backup."""

    id: str
    project_id: str
    name: str
    backup_type: str
    status: str
    size_bytes: int | None = None
    db_size_bytes: int | None = None
    files_size_bytes: int | None = None
    location: str | None = None
    note: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    verified: bool | None = None
    verified_at: datetime | None = None
    checksum: str | None = None
    total_files: int | None = None
    verification_json: dict[str, object] | None = None


class BackupListResponse(BaseModel):
    """Response model for listing backups."""

    backups: list[BackupResponse]
    total: int


class RestoreRequest(BaseModel):
    """Request model for restore operation."""

    dry_run: bool = False
    db_only: bool = False
    files_only: bool = False


class RestoreResponse(BaseModel):
    """Response model for restore operation."""

    task_id: str | None = None
    status: str
    message: str


class ScheduleRequest(BaseModel):
    """Request model for backup schedule."""

    enabled: bool
    frequency: str  # 'daily', 'weekly', 'monthly'
    retention_days: int = 14


class ScheduleResponse(BaseModel):
    """Response model for backup schedule."""

    id: int
    project_id: str
    enabled: bool
    frequency: str
    retention_days: int
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StorageSummaryResponse(BaseModel):
    """Response model for storage usage summary."""

    total_count: int
    total_bytes: int
    by_status: dict[str, int]
