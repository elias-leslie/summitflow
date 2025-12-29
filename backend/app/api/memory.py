"""Memory API - Memory system statistics, health, and global queries.

This module provides REST API endpoints for memory system monitoring.
It acts as an orchestrator that includes sub-routers for specific domains:

- memory_stats: System-wide memory statistics
- memory_search: Unified search across memory entities
- memory_backfill: Mine session history for patterns
- memory_health: Health checks and corrections
- memory_patterns: Pattern operations (list, bulk approve/reject, promote, feedback)
- memory_observations: Observation listing and bulk operations
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    memory_backfill,
    memory_health,
    memory_observations,
    memory_patterns,
    memory_search,
    memory_stats,
)

# Re-export models for backwards compatibility
from .memory_models import (
    ApplyApprovedResponse,
    BackfillRequest,
    BackfillResponse,
    BulkObservationItem,
    BulkObservationRequest,
    BulkObservationResponse,
    BulkPatternRequest,
    BulkPatternResponse,
    DeepReviewResponse,
    FilteringMetrics,
    HealthCorrection,
    HealthResponse,
    HealthWarning,
    LifecycleStats,
    MemoryStats,
    PaginatedResponse,
    PatternFeedbackRequest,
    PatternFeedbackResponse,
    PromotePatternResponse,
    SearchResponse,
    SearchResult,
)

# Create main router that includes all sub-routers
router = APIRouter()

# Include all sub-routers (they all use prefix="" since we add /api in main.py)
router.include_router(memory_stats.router, tags=["memory"])
router.include_router(memory_search.router, tags=["memory"])
router.include_router(memory_backfill.router, tags=["memory"])
router.include_router(memory_health.router, tags=["memory"])
router.include_router(memory_patterns.router, tags=["memory"])
router.include_router(memory_observations.router, tags=["memory"])

# Re-export everything for backwards compatibility
__all__ = [
    # Models
    "ApplyApprovedResponse",
    "BackfillRequest",
    "BackfillResponse",
    "BulkObservationItem",
    "BulkObservationRequest",
    "BulkObservationResponse",
    "BulkPatternRequest",
    "BulkPatternResponse",
    "DeepReviewResponse",
    "FilteringMetrics",
    "HealthCorrection",
    "HealthResponse",
    "HealthWarning",
    "LifecycleStats",
    "MemoryStats",
    "PaginatedResponse",
    "PatternFeedbackRequest",
    "PatternFeedbackResponse",
    "PromotePatternResponse",
    "SearchResponse",
    "SearchResult",
    "router",
]
