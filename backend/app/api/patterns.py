"""Patterns API endpoints.

Provides access to learned patterns with full lifecycle management.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.memory import PatternService, ReflectionService

router = APIRouter()


class PatternStatusUpdate(BaseModel):
    """Request body for updating pattern status."""

    status: str
    reason: str | None = None


class PatternMerge(BaseModel):
    """Request body for merging patterns."""

    pattern_ids: list[str]
    merged_title: str
    merged_content: str
    rationale: str | None = None


class ReflectionTrigger(BaseModel):
    """Request body for triggering reflection."""

    limit: int = 10
    auto_apply: bool = True


@router.get("/{project_id}/patterns")
async def list_patterns(
    project_id: str,
    status: str | None = Query(None, description="Filter by status"),
    pattern_type: str | None = Query(None, description="Filter by type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List patterns for a project.

    Args:
        project_id: Project ID
        status: Filter by status (pending, approved, applied, rejected, merged)
        pattern_type: Filter by type (rule, preference, anti-pattern)
        limit: Max patterns to return
        offset: Pagination offset

    Returns:
        List of patterns with metadata
    """
    service = PatternService(project_id)

    patterns = service.list_patterns(
        status=status,
        pattern_type=pattern_type,
        limit=limit,
        offset=offset,
    )

    # Get counts by status
    pending = service.list_patterns(status="pending", limit=1000)
    approved = service.list_patterns(status="approved", limit=1000)
    applied = service.list_patterns(status="applied", limit=1000)

    return {
        "patterns": patterns,
        "total": len(patterns),
        "counts": {
            "pending": len(pending),
            "approved": len(approved),
            "applied": len(applied),
        },
        "limit": limit,
        "offset": offset,
    }


@router.get("/{project_id}/patterns/stale")
async def get_stale_patterns(
    project_id: str,
    days: int = Query(30, ge=1, le=365),
) -> dict[str, Any]:
    """Get patterns that haven't been used recently.

    Stale patterns are applied but not used within the threshold period.

    Args:
        project_id: Project ID
        days: Days threshold for staleness

    Returns:
        List of stale patterns
    """
    service = PatternService(project_id)
    stale = service.get_stale_patterns(days_threshold=days)

    return {
        "stale_patterns": stale,
        "total": len(stale),
        "days_threshold": days,
    }


@router.get("/{project_id}/patterns/{pattern_id}")
async def get_pattern(
    project_id: str,
    pattern_id: str,
) -> dict[str, Any]:
    """Get a specific pattern.

    Args:
        project_id: Project ID
        pattern_id: Pattern ID

    Returns:
        The pattern

    Raises:
        HTTPException: If pattern not found
    """
    service = PatternService(project_id)
    pattern = service.get_pattern(pattern_id)

    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    return pattern


@router.patch("/{project_id}/patterns/{pattern_id}")
async def update_pattern_status(
    project_id: str,
    pattern_id: str,
    body: PatternStatusUpdate,
) -> dict[str, Any]:
    """Update pattern status.

    Valid transitions:
    - pending -> approved, rejected
    - approved -> applied, rejected
    - rejected -> pending (re-review)

    Args:
        project_id: Project ID
        pattern_id: Pattern ID
        body: Status update data

    Returns:
        Updated pattern

    Raises:
        HTTPException: If pattern not found or transition invalid
    """
    service = PatternService(project_id)

    try:
        pattern = service.update_status(
            pattern_id=pattern_id,
            new_status=body.status,
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    return pattern


@router.post("/{project_id}/patterns/{pattern_id}/apply")
async def apply_pattern(
    project_id: str,
    pattern_id: str,
    project_path: str = Query(..., description="Path to project root"),
) -> dict[str, Any]:
    """Apply a pattern to .claude/rules/.

    The pattern must be in 'approved' status.

    Args:
        project_id: Project ID
        pattern_id: Pattern ID
        project_path: Path to project root for writing rules

    Returns:
        Updated pattern with applied status

    Raises:
        HTTPException: If pattern not found or not approved
    """
    service = PatternService(project_id, project_path=project_path)

    try:
        pattern = service.apply_pattern(pattern_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    return pattern


@router.post("/{project_id}/patterns/{pattern_id}/undo")
async def undo_pattern_application(
    project_id: str,
    pattern_id: str,
) -> dict[str, Any]:
    """Undo pattern application (move back to approved).

    Note: This only changes the status, it doesn't remove the pattern
    from .claude/rules/ file. Manual cleanup may be needed.

    Args:
        project_id: Project ID
        pattern_id: Pattern ID

    Returns:
        Updated pattern with approved status

    Raises:
        HTTPException: If pattern not found
    """
    service = PatternService(project_id)
    pattern = service.get_pattern(pattern_id)

    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    if pattern["status"] != "applied":
        raise HTTPException(
            status_code=400,
            detail=f"Can only undo applied patterns, current status: {pattern['status']}",
        )

    # Move back to approved
    try:
        # Use storage directly since update_status won't allow this transition
        from ..storage import memory as memory_storage

        memory_storage.update_pattern_status(pattern_id, "approved")
        return service.get_pattern(pattern_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/{project_id}/patterns/merge")
async def merge_patterns(
    project_id: str,
    body: PatternMerge,
) -> dict[str, Any]:
    """Merge multiple patterns into one.

    Creates a new pattern and marks originals as merged.

    Args:
        project_id: Project ID
        body: Merge data with pattern IDs and merged content

    Returns:
        The new merged pattern

    Raises:
        HTTPException: If validation fails
    """
    service = PatternService(project_id)

    try:
        merged = service.merge_patterns(
            pattern_ids=body.pattern_ids,
            merged_title=body.merged_title,
            merged_content=body.merged_content,
            rationale=body.rationale,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return merged


@router.post("/{project_id}/reflection/trigger")
async def trigger_reflection(
    project_id: str,
    project_path: str | None = Query(None, description="Path to project root"),
    body: ReflectionTrigger | None = None,
) -> dict[str, Any]:
    """Manually trigger reflection analysis.

    Analyzes recent diary entries and generates pattern suggestions.

    Args:
        project_id: Project ID
        project_path: Path to project root for auto-applying patterns
        body: Reflection options

    Returns:
        Reflection results with suggestions and patterns created
    """
    if body is None:
        body = ReflectionTrigger()

    service = ReflectionService(
        project_id=project_id,
        project_path=project_path,
    )

    result = service.analyze_diary(
        limit=body.limit,
        auto_apply=body.auto_apply,
    )

    return {
        "diary_entries_processed": len(result.diary_ids_processed),
        "suggestions": len(result.suggestions),
        "patterns_created": result.patterns_created,
        "patterns_auto_applied": result.patterns_auto_applied,
        "tokens_used": result.tokens_used,
        "errors": result.errors,
    }
