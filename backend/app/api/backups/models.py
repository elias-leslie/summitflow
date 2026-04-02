"""Pydantic models for backup API requests and responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

BackendType = Literal["smb"]
SourceType = Literal["project", "config", "infrastructure", "workspace"]
Frequency = Literal["hourly", "daily", "weekly", "monthly"]


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
    source_id: str | None = None


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


class BackupSourceCreate(BaseModel):
    """Request model for registering a backup source."""

    id: str
    name: str
    path: str
    source_type: SourceType = "project"
    project_id: str | None = None


class BackupSourceUpdate(BaseModel):
    """Request model for updating a backup source."""

    name: str | None = None
    enabled: bool | None = None
    frequency: Frequency | None = None
    retention_days: int | None = None
    path: str | None = None


class BackupSourceResponse(BaseModel):
    """Response model for a backup source."""

    id: str
    name: str
    path: str
    source_type: str
    project_id: str | None = None
    enabled: bool
    frequency: str
    retention_days: int
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_drill_at: datetime | None = None
    last_drill_ok: bool | None = None
    last_drill_backup_id: str | None = None


class StorageSummaryResponse(BaseModel):
    """Response model for storage usage summary."""

    total_count: int
    total_bytes: int
    by_status: dict[str, int]


# ─── Storage Backend Models ─────────────────────────────────────


class StorageBackendCreate(BaseModel):
    """Request model for creating a storage backend."""

    name: str
    backend_type: BackendType = "smb"
    config: dict[str, object] | None = None
    is_default: bool = False


class StorageBackendUpdate(BaseModel):
    """Request model for updating a storage backend."""

    name: str | None = None
    config: dict[str, object] | None = None
    is_default: bool | None = None
    enabled: bool | None = None


class StorageBackendResponse(BaseModel):
    """Response model for a storage backend."""

    id: str
    name: str
    backend_type: str
    config: dict[str, object]
    is_default: bool
    enabled: bool
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── Backup Health Models ────────────────────────────────────────


class BackupHealthItem(BaseModel):
    """Health status for a single backup source."""

    source_id: str
    source_name: str
    source_type: str
    enabled: bool
    health_status: str  # green | yellow | red
    last_success_at: str | None = None
    next_run_at: str | None = None
    failure_count_7d: int = 0
    pending_upload_count: int = 0
    last_restore_tested_at: str | None = None
    last_restore_test_ok: bool | None = None
    # Phase 4: extended health fields
    latest_backup_age_hours: float | None = None
    latest_restore_test_age_hours: float | None = None
    restore_test_backup_id: str | None = None
    coverage_complete: bool | None = None
    pitr_supported: bool = False
    restore_confidence: str | None = None  # verified | stale | partial | untested
    # Drill tracking
    last_drill_at: str | None = None
    last_drill_ok: bool | None = None
    last_drill_backup_id: str | None = None


class BackupHealthResponse(BaseModel):
    """Response model for backup health summary."""

    sources: list[BackupHealthItem]
    pending_upload_count: int = 0


# ─── Coverage Contract Models ──────────────────────────────────


class CoverageComponentResponse(BaseModel):
    """A single component of the infra coverage contract."""

    key: str
    label: str
    category: str  # required | optional | excluded
    description: str
    archive_marker: str | None = None
    reason: str | None = None


class CoverageVerificationComponent(BaseModel):
    """Verification result for a single coverage component."""

    key: str
    label: str
    category: str
    present: bool
    error: str | None = None


class CoverageVerificationResult(BaseModel):
    """Result of verifying an archive against the coverage contract."""

    complete: bool
    required_count: int
    present_count: int
    missing: list[str]
    components: list[CoverageVerificationComponent]


class CoverageResponse(BaseModel):
    """Full coverage contract with optional verification."""

    contract: list[CoverageComponentResponse]
    verified: bool = False
    result: CoverageVerificationResult | None = None


# ─── Restore Drill Models ──────────────────────────────────────


class DrillComponentResult(BaseModel):
    """Result of one component in a restore drill."""

    key: str
    ok: bool
    error: str | None = None


class RestoreDrillResult(BaseModel):
    """Result of a full infrastructure restore drill."""

    ok: bool
    backup_id: str | None = None
    components: list[DrillComponentResult]
    duration_ms: int | None = None
    drilled_at: str | None = None
