"""Memory Health API - Health checks and corrections.

Endpoints:
- GET /memory/health - Get comprehensive memory health status
- POST /memory/health/check - Run health check with auto-correction
- GET /memory/deep-review - Get deep review of project instruction surfaces
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from .memory_models import (
    DeepReviewResponse,
    HealthCorrection,
    HealthResponse,
    HealthWarning,
)

router = APIRouter()


@router.get("/memory/health", response_model=HealthResponse)
async def get_memory_health(
    project_id: str = Query(..., description="Project ID to check"),
) -> HealthResponse:
    """Get comprehensive memory health status.

    Returns health metrics including:
    - Filter statistics (received, queued, skipped)
    - Observation distribution by type
    - Pattern status breakdown
    - Embedding coverage
    - Approved patterns waiting to be applied
    """
    from ..services.memory.health_checker import MemoryHealthChecker

    checker = MemoryHealthChecker(project_id)
    metrics = checker.get_health_metrics()
    recommendations = checker.get_threshold_recommendations()

    return HealthResponse(
        status="healthy",
        corrections=[],
        warnings=[],
        metrics=metrics,
        recommendations=recommendations if recommendations else None,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.post("/memory/health/check", response_model=HealthResponse)
async def run_health_check(
    project_id: str = Query(..., description="Project ID to check"),
) -> HealthResponse:
    """Run health check with auto-correction.

    This endpoint:
    1. Checks for approved patterns and applies them
    2. Checks filter rate and adds warnings if too high
    3. Checks for missing observation types
    4. Returns the full report with corrections and warnings
    """
    from ..services.memory.health_checker import MemoryHealthChecker

    checker = MemoryHealthChecker(project_id)
    report = checker.check_and_correct()

    return HealthResponse(
        status=report.status,
        corrections=[
            HealthCorrection(
                type=c.correction_type,
                description=c.description,
                details=c.details,
                timestamp=c.timestamp,
            )
            for c in report.corrections
        ],
        warnings=[
            HealthWarning(
                type=w.warning_type,
                message=w.message,
                severity=w.severity,
                details=w.details,
            )
            for w in report.warnings
        ],
        metrics=report.metrics,
        stale_rules=report.stale_rules,
        auto_archived=report.auto_archived,
        sync_suggestions=report.sync_suggestions,
        doc_conflicts=report.doc_conflicts,
        timestamp=report.timestamp,
    )


@router.get("/memory/deep-review", response_model=DeepReviewResponse)
async def get_deep_review(
    project_id: str = Query(..., description="Project ID to review"),
) -> DeepReviewResponse:
    """Get comprehensive deep review of project instruction surfaces.

    Analyzes:
    - CLAUDE.md and AGENTS.md sections
    - Project and global rules files
    - Broken references to files/functions
    - Token waste calculation

    Note: LLM review is not included in this sync endpoint.
    Use POST /memory/deep-review for full LLM-powered analysis.
    """
    from ..services.memory.health_checker import MemoryHealthChecker

    checker = MemoryHealthChecker(project_id)
    report = checker.deep_review()

    return DeepReviewResponse(
        claude_md_sections=report.claude_md_sections,
        agents_md_sections=report.agents_md_sections,
        rules_files=report.rules_files,
        global_rules_files=report.global_rules_files,
        broken_refs=[
            {
                "doc_file": r.doc_file,
                "line_number": r.line_number,
                "reference": r.reference,
                "ref_type": r.ref_type,
                "reason": r.reason,
            }
            for r in report.broken_refs
        ],
        stale_sections=[
            {
                "doc_file": s.doc_file,
                "section_title": s.section_title,
                "line_start": s.line_start,
                "staleness_reason": s.staleness_reason,
                "confidence": s.confidence,
            }
            for s in report.stale_sections
        ],
        token_waste=report.token_waste,
        timestamp=report.timestamp,
    )
