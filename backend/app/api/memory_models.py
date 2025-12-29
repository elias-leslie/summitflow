"""Memory API shared models.

Pydantic models used across memory API endpoints.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class FilteringMetrics(BaseModel):
    """Tool filtering metrics."""

    tools_received: int
    tools_queued: int
    tools_skipped: int
    skip_reasons: dict[str, int]
    filter_effectiveness: float  # Percentage of tools filtered


class LifecycleStats(BaseModel):
    """Lifecycle health metrics for memory system."""

    failed_queue_count: int  # Queue items in failed status
    stuck_queue_count: int  # Queue items stuck in processing > 1 hour
    oldest_pending_age_minutes: int | None  # Age of oldest pending queue item
    unreflected_diary_count: int  # Diary entries never reflected
    stale_patterns_count: int  # Applied patterns unused for 30+ days
    pattern_status_breakdown: dict[str, int]  # Count by status (pending, approved, etc.)


class MemoryStats(BaseModel):
    """Memory system statistics."""

    queue_depth: int
    queue_pending: int
    observations_today: int
    observation_success_rate: float
    token_spend_24h: int
    health: str  # 'healthy', 'degraded', 'unhealthy'
    health_details: dict[str, Any] | None = None
    filtering: FilteringMetrics | None = None
    lifecycle: LifecycleStats | None = None


class PaginatedResponse(BaseModel):
    """Generic paginated response with total count."""

    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class SearchResult(BaseModel):
    """Unified search result item."""

    entity_type: str  # 'observation', 'pattern', 'user_prompt', 'diary'
    id: str
    title: str | None
    summary: str | None
    score: float
    created_at: str | None
    data: dict[str, Any]


class SearchResponse(BaseModel):
    """Unified search response."""

    query: str
    use_semantic: bool
    total: int
    results: list[SearchResult]


class BulkPatternRequest(BaseModel):
    """Request body for bulk pattern operations."""

    pattern_ids: list[str]
    reason: str | None = None


class BulkPatternResponse(BaseModel):
    """Response for bulk pattern operations."""

    updated: int
    failed: int
    errors: list[str]


class BackfillRequest(BaseModel):
    """Request body for history backfill."""

    project_id: str
    sessions_limit: int = 10
    dry_run: bool = True


class BackfillResponse(BaseModel):
    """Response from history backfill operation."""

    project_id: str
    sessions_found: int
    sessions_processed: int
    patterns_extracted: int
    observations_created: int
    dry_run: bool
    errors: list[str]
    session_stats: dict[str, Any] | None = None


class HealthWarning(BaseModel):
    """A health warning."""

    type: str
    message: str
    severity: str
    details: dict[str, Any] | None = None


class HealthCorrection(BaseModel):
    """A correction that was applied."""

    type: str
    description: str
    details: dict[str, Any] | None = None
    timestamp: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    corrections: list[HealthCorrection]
    warnings: list[HealthWarning]
    metrics: dict[str, Any]
    recommendations: list[dict[str, Any]] | None = None
    stale_rules: list[dict[str, Any]] = []
    auto_archived: list[dict[str, Any]] = []
    sync_suggestions: list[dict[str, Any]] = []
    doc_conflicts: list[dict[str, Any]] = []
    timestamp: str


class ApplyApprovedResponse(BaseModel):
    """Response from apply-approved endpoint."""

    applied_count: int
    pattern_ids: list[str]
    errors: list[str]


class DeepReviewResponse(BaseModel):
    """Response from deep review endpoint."""

    claude_md_sections: list[dict[str, Any]] = []
    agents_md_sections: list[dict[str, Any]] = []
    rules_files: list[dict[str, Any]] = []
    global_rules_files: list[dict[str, Any]] = []
    broken_refs: list[dict[str, Any]] = []
    stale_sections: list[dict[str, Any]] = []
    token_waste: dict[str, Any] = {}
    timestamp: str


class BulkObservationItem(BaseModel):
    """Single observation item for bulk creation."""

    observation_type: str
    title: str
    narrative: str | None = None
    confidence: float = 0.7
    files_modified: list[str] | None = None
    concepts: list[str] | None = None
    facts: dict[str, Any] | None = None


class BulkObservationRequest(BaseModel):
    """Request body for bulk observation creation."""

    project_id: str
    session_id: str
    agent_type: str = "refactor"
    observations: list[BulkObservationItem]


class BulkObservationResponse(BaseModel):
    """Response from bulk observation creation."""

    created_count: int
    skipped_count: int
    errors: list[str]


class PromotePatternResponse(BaseModel):
    """Response for pattern promotion endpoint."""

    promoted: bool
    global_pattern_id: str | None
    source_pattern_id: str
    error: str | None


class PatternFeedbackRequest(BaseModel):
    """Request body for pattern feedback."""

    outcome: Literal["success", "failure"]
    context: str | None = None  # Optional context about what happened


class PatternFeedbackResponse(BaseModel):
    """Response from pattern feedback."""

    pattern_id: str
    previous_confidence: float
    new_confidence: float
    new_status: str | None  # Only set if status changed
    feedback_count: int  # Total feedback entries for this pattern
