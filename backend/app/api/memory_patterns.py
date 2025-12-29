"""Memory Patterns API - Pattern operations.

Endpoints:
- GET /patterns - List patterns globally
- POST /patterns/bulk-approve - Bulk approve patterns
- POST /patterns/bulk-reject - Bulk reject patterns
- POST /memory/patterns/apply-approved - Apply all approved patterns
- POST /memory/patterns/{pattern_id}/promote - Promote pattern to global
- POST /memory/patterns/{pattern_id}/feedback - Record pattern feedback
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Path, Query

from ..storage import memory as memory_storage
from .memory_models import (
    ApplyApprovedResponse,
    BulkPatternRequest,
    BulkPatternResponse,
    PaginatedResponse,
    PatternFeedbackRequest,
    PatternFeedbackResponse,
    PromotePatternResponse,
)

router = APIRouter()


@router.get("/patterns", response_model=PaginatedResponse)
async def list_patterns_global(
    project_id: str | None = Query(None, description="Filter by project"),
    status: str | None = Query(None, description="Filter by status"),
    action: str | None = Query(None, description="Filter by action type"),
    pattern_type: str | None = Query(None, description="Filter by pattern type"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse:
    """List patterns across all projects.

    Use project_id query param to filter to a specific project.
    Returns patterns sorted by created_at descending (newest first).
    """
    items = memory_storage.list_patterns(
        project_id=project_id,
        status=status,
        action=action,
        pattern_type=pattern_type,
        limit=limit,
        offset=offset,
    )
    total = memory_storage.count_patterns(
        project_id=project_id,
        status=status,
        action=action,
        pattern_type=pattern_type,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


def _bulk_update_pattern_status(
    pattern_ids: list[str],
    status: str,
    reviewed_by: str,
) -> BulkPatternResponse:
    """Helper to update multiple patterns with the same status."""
    updated = 0
    failed = 0
    errors: list[str] = []

    for pattern_id in pattern_ids:
        try:
            success = memory_storage.update_pattern_status(
                pattern_id=pattern_id,
                status=status,
                reviewed_by=reviewed_by,
            )
            if success:
                updated += 1
            else:
                failed += 1
                errors.append(f"Pattern {pattern_id} not found")
        except Exception as e:
            failed += 1
            errors.append(f"Pattern {pattern_id}: {e!s}")

    return BulkPatternResponse(updated=updated, failed=failed, errors=errors)


@router.post("/patterns/bulk-approve", response_model=BulkPatternResponse)
async def bulk_approve_patterns(
    request: BulkPatternRequest,
) -> BulkPatternResponse:
    """Bulk approve multiple patterns.

    Transitions patterns from 'pending' to 'approved'.
    """
    return _bulk_update_pattern_status(
        pattern_ids=request.pattern_ids,
        status="approved",
        reviewed_by=request.reason or "bulk-approve",
    )


@router.post("/patterns/bulk-reject", response_model=BulkPatternResponse)
async def bulk_reject_patterns(
    request: BulkPatternRequest,
) -> BulkPatternResponse:
    """Bulk reject multiple patterns.

    Transitions patterns from 'pending' to 'rejected'.
    """
    return _bulk_update_pattern_status(
        pattern_ids=request.pattern_ids,
        status="rejected",
        reviewed_by=request.reason or "bulk-reject",
    )


@router.post("/memory/patterns/apply-approved", response_model=ApplyApprovedResponse)
async def apply_approved_patterns(
    project_id: str = Query(..., description="Project ID"),
) -> ApplyApprovedResponse:
    """Bulk apply all approved patterns with confidence >= 0.7.

    This endpoint:
    1. Gets all approved patterns with high confidence
    2. Writes each to learned-patterns.md
    3. Updates database status to 'applied'
    4. Returns count and list of applied pattern IDs
    """
    from ..services.memory.health_checker import MemoryHealthChecker

    checker = MemoryHealthChecker(project_id)
    patterns = checker._get_approved_patterns(project_id)

    if not patterns:
        return ApplyApprovedResponse(
            applied_count=0,
            pattern_ids=[],
            errors=["No approved patterns found with confidence >= 0.7"],
        )

    applied_count = checker._apply_approved_patterns(project_id, patterns)
    pattern_ids = [str(p.get("id")) for p in patterns[:applied_count] if p.get("id")]

    return ApplyApprovedResponse(
        applied_count=applied_count,
        pattern_ids=pattern_ids,
        errors=[],
    )


@router.post("/memory/patterns/{pattern_id}/promote", response_model=PromotePatternResponse)
async def promote_pattern_to_global(
    pattern_id: str = Path(..., description="Pattern ID to promote"),
    project_id: str = Query(..., description="Source project ID"),
) -> PromotePatternResponse:
    """Promote a pattern to global scope for use across all projects.

    Requirements:
    - Pattern must have confidence >= 0.9
    - Creates a copy with project_id='_global_'
    - Global patterns are written to ~/.claude/rules/learned-patterns.md

    Args:
        pattern_id: ID of the pattern to promote
        project_id: The source project the pattern belongs to
    """
    from ..services.memory.pattern_service import PatternService

    try:
        service = PatternService(project_id=project_id)
        global_pattern = service.promote_to_global(pattern_id)

        return PromotePatternResponse(
            promoted=True,
            global_pattern_id=global_pattern.get("id"),
            source_pattern_id=pattern_id,
            error=None,
        )
    except ValueError as e:
        return PromotePatternResponse(
            promoted=False,
            global_pattern_id=None,
            source_pattern_id=pattern_id,
            error=str(e),
        )


@router.post("/memory/patterns/{pattern_id}/feedback", response_model=PatternFeedbackResponse)
async def record_pattern_feedback(
    request: PatternFeedbackRequest,
    pattern_id: str = Path(..., description="Pattern ID to provide feedback for"),
) -> PatternFeedbackResponse:
    """Record feedback for a pattern to adjust its confidence.

    This endpoint:
    - On success: Increases confidence by 0.05 (max 1.0)
    - On failure: Decreases confidence by 0.1 (min 0.0)
    - After 3 consecutive failures: Auto-flags pattern for review

    The feedback is stored in the pattern's feedback_history JSONB field
    with timestamp, outcome, context, and confidence delta.

    Args:
        pattern_id: ID of the pattern to provide feedback for
        request: Feedback with outcome ('success' or 'failure') and optional context
    """
    # Get current pattern (validation of outcome is handled by Pydantic Literal type)
    pattern = memory_storage.get_pattern(pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail=f"Pattern {pattern_id} not found")

    previous_confidence = pattern.get("confidence", 0.7)
    feedback_history = pattern.get("feedback_history") or []

    # Calculate new confidence
    if request.outcome == "success":
        new_confidence = min(1.0, previous_confidence + 0.05)
    else:
        new_confidence = max(0.0, previous_confidence - 0.1)

    # Add feedback entry
    feedback_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "outcome": request.outcome,
        "context": request.context,
        "confidence_before": previous_confidence,
        "confidence_after": new_confidence,
    }
    feedback_history.append(feedback_entry)

    # Check for 3 consecutive failures -> needs_review
    new_status = None
    recent_outcomes = [f.get("outcome") for f in feedback_history[-3:]]
    if (
        len(recent_outcomes) >= 3
        and all(o == "failure" for o in recent_outcomes)
        and pattern.get("status") != "needs_review"
    ):
        new_status = "needs_review"

    # Update pattern in database
    memory_storage.update_pattern_feedback(
        pattern_id=pattern_id,
        confidence=new_confidence,
        feedback_history=feedback_history,
        status=new_status,
    )

    return PatternFeedbackResponse(
        pattern_id=pattern_id,
        previous_confidence=previous_confidence,
        new_confidence=new_confidence,
        new_status=new_status,
        feedback_count=len(feedback_history),
    )
