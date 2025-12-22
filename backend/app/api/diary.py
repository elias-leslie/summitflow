"""Diary API endpoints.

Provides access to session diary entries for the learning system.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.memory import DiaryService

router = APIRouter()


class DiaryEntryCreate(BaseModel):
    """Request body for creating a diary entry."""

    session_id: str
    agent_type: str
    outcome: str = "neutral"
    task_id: str | None = None
    duration_seconds: int | None = None
    tokens_used: int | None = None
    observation_type: str | None = None
    concepts: list[str] | None = None
    what_worked: list[str] | None = None
    what_failed: list[str] | None = None
    user_corrections: list[str] | None = None
    patterns_used: list[str] | None = None


@router.get("/{project_id}/diary")
async def list_diary_entries(
    project_id: str,
    outcome: str | None = Query(None, description="Filter by outcome"),
    unreflected_only: bool = Query(False, description="Only unreflected entries"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List diary entries for a project.

    Args:
        project_id: Project ID
        outcome: Filter by outcome (success, failure, partial, neutral)
        unreflected_only: Only return entries not yet processed by reflection
        limit: Max entries to return
        offset: Pagination offset

    Returns:
        List of diary entries with metadata
    """
    service = DiaryService(project_id)

    entries = service.get_entries(
        limit=limit,
        offset=offset,
        outcome=outcome,
        unreflected_only=unreflected_only,
    )

    unprocessed_count = service.get_unprocessed_count()

    return {
        "entries": entries,
        "total": len(entries),
        "unprocessed_count": unprocessed_count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{project_id}/diary/{entry_id}")
async def get_diary_entry(
    project_id: str,
    entry_id: str,
) -> dict[str, Any]:
    """Get a specific diary entry.

    Args:
        project_id: Project ID
        entry_id: Diary entry ID

    Returns:
        The diary entry

    Raises:
        HTTPException: If entry not found
    """
    service = DiaryService(project_id)
    entry = service.get_entry(entry_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Diary entry not found")

    return entry


@router.post("/{project_id}/diary", status_code=201)
async def create_diary_entry(
    project_id: str,
    body: DiaryEntryCreate,
) -> dict[str, Any]:
    """Create a diary entry manually.

    Most diary entries are created automatically when sessions end,
    but this endpoint allows manual creation for testing or special cases.

    Args:
        project_id: Project ID
        body: Diary entry data

    Returns:
        The created diary entry
    """
    service = DiaryService(project_id)

    entry = service.create_entry(
        session_id=body.session_id,
        agent_type=body.agent_type,
        outcome=body.outcome,
        task_id=body.task_id,
        duration_seconds=body.duration_seconds,
        tokens_used=body.tokens_used,
        observation_type=body.observation_type,
        concepts=body.concepts,
        what_worked=body.what_worked,
        what_failed=body.what_failed,
        user_corrections=body.user_corrections,
        patterns_used=body.patterns_used,
    )

    return entry


@router.get("/{project_id}/diary/stats")
async def get_diary_stats(
    project_id: str,
) -> dict[str, Any]:
    """Get diary statistics for a project.

    Args:
        project_id: Project ID

    Returns:
        Statistics about diary entries
    """
    service = DiaryService(project_id)

    # Get recent entries for statistics
    all_entries = service.get_entries(limit=100)
    unprocessed = service.get_unprocessed_count()

    # Calculate outcome distribution
    outcomes = {"success": 0, "failure": 0, "partial": 0, "neutral": 0}
    for entry in all_entries:
        outcome = entry.get("outcome", "neutral")
        if outcome in outcomes:
            outcomes[outcome] += 1

    # Calculate total tokens
    total_tokens = sum(e.get("tokens_used", 0) or 0 for e in all_entries)

    return {
        "total_entries": len(all_entries),
        "unprocessed_count": unprocessed,
        "outcome_distribution": outcomes,
        "total_tokens": total_tokens,
    }
