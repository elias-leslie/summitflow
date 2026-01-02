"""Scan history Pydantic models for request/response validation.

Models for tracking explorer scan executions with trigger metadata
and metrics for trend visualization.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- Core Models ----


class ScanHistoryEntry(BaseModel):
    """Single scan history record."""

    id: int
    project_id: str
    scan_type: str  # 'file', 'page', 'endpoint', 'database', 'task', 'full'

    # Trigger metadata
    triggered_by: str  # 'manual', 'refactor_it', 'daily_qa_scan', 'audit_it', 'celery_beat'
    triggered_by_session: str | None = None
    triggered_by_user: str | None = None
    trigger_context: dict[str, Any] = Field(default_factory=dict)

    # Timing
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None

    # Status
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    error_message: str | None = None

    # Metrics
    metrics: dict[str, Any] = Field(default_factory=dict)
    entries_found: int = 0
    entries_saved: int = 0

    # Comparison
    previous_scan_id: int | None = None
    metrics_delta: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime

    class Config:
        from_attributes = True


# ---- Sparkline/Chart Data ----


class SparklineDataPoint(BaseModel):
    """Single data point for sparkline chart."""

    date: str  # YYYY-MM-DD
    complexity: float | None = None  # Average complexity score
    scan_count: int = 0
    high_priority_count: int = 0  # Issues with severity 'high' or 'critical'


class SparklineData(BaseModel):
    """Aggregated data for sparkline visualization."""

    dates: list[str]  # YYYY-MM-DD
    complexity: list[float | None]  # Daily average complexity
    targets: list[int]  # Daily scan counts
    high_priority: list[int]  # Daily high priority issue counts


# ---- Summary Statistics ----


class TriggerBreakdown(BaseModel):
    """Breakdown of scans by trigger type."""

    trigger: str
    count: int
    percentage: float = 0.0


class ScanHistorySummary(BaseModel):
    """Summary statistics for scan history."""

    total_scans: int = 0
    avg_duration_ms: float | None = None
    complexity_trend: Literal["improving", "stable", "degrading", "unknown"] = "unknown"
    most_active_trigger: str | None = None
    triggers_breakdown: list[TriggerBreakdown] = Field(default_factory=list)


# ---- Response Models ----


class ScanHistoryResponse(BaseModel):
    """Full response for scan history endpoint."""

    scans: list[ScanHistoryEntry] = Field(default_factory=list)
    sparkline_data: SparklineData
    summary: ScanHistorySummary


class ScanComparison(BaseModel):
    """Before/after comparison between two scans."""

    before_scan: ScanHistoryEntry
    after_scan: ScanHistoryEntry
    before_metrics: dict[str, Any] = Field(default_factory=dict)
    after_metrics: dict[str, Any] = Field(default_factory=dict)
    delta: dict[str, Any] = Field(default_factory=dict)  # Absolute difference
    delta_pct: dict[str, float] = Field(default_factory=dict)  # Percentage change


# ---- Request Models ----


class ScanStartRequest(BaseModel):
    """Request to start a scan with trigger metadata."""

    scan_type: str = "full"
    triggered_by: str = "manual"
    triggered_by_session: str | None = None
    triggered_by_user: str | None = None
    trigger_context: dict[str, Any] = Field(default_factory=dict)


class ScanCompleteRequest(BaseModel):
    """Request to mark a scan as complete."""

    status: Literal["completed", "failed", "cancelled"] = "completed"
    error_message: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    entries_found: int = 0
    entries_saved: int = 0
