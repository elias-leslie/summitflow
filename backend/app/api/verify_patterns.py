"""Verify Patterns API - Endpoints for pattern library feedback loop.

Provides:
- POST /record - Record verify_command outcome
- GET /lookup - Get stats for a command pattern
- GET /suggest - Get known-good patterns by type
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..storage import verify_patterns as store

router = APIRouter(prefix="/verify-patterns", tags=["verify-patterns"])


class RecordOutcomeRequest(BaseModel):
    """Request to record a verify_command outcome."""

    command: str
    success: bool
    duration_ms: int = 0
    exit_code: int = 0


class PatternStatsResponse(BaseModel):
    """Response with pattern statistics."""

    success_rate: float | None
    total_runs: int
    avg_duration_ms: int
    pattern_type: str
    last_outcome_at: str | None = None
    found: bool


class SuggestedPattern(BaseModel):
    """A suggested high-success pattern."""

    command_example: str
    normalized_pattern: str
    success_rate: float
    total_runs: int
    avg_duration_ms: int


@router.post("/record")
async def record_outcome(body: RecordOutcomeRequest) -> dict[str, Any]:
    """Record the outcome of a verify_command execution.

    This is called after each step verification to build the pattern library.
    """
    result = store.record_outcome(
        command=body.command,
        success=body.success,
        duration_ms=body.duration_ms,
        exit_code=body.exit_code,
    )
    return result


@router.get("/lookup")
async def lookup_pattern(command: str = Query(..., description="The verify_command to look up")) -> PatternStatsResponse:
    """Get statistics for a verify_command pattern.

    Use this during planning to check historical success rates.
    Patterns with <70% success rate should trigger a warning.
    """
    stats = store.get_pattern_stats(command)
    return PatternStatsResponse(**stats)


@router.get("/suggest")
async def suggest_patterns(
    type: str = Query(..., description="Pattern type: deploy, grep, curl, test"),
    min_success_rate: float = Query(70.0, description="Minimum success rate (default 70%)"),
    limit: int = Query(5, description="Maximum patterns to return"),
) -> list[SuggestedPattern]:
    """Get known-good patterns of a specific type.

    Use this during planning to find proven alternatives for common verification needs.
    """
    patterns = store.get_suggested_patterns(
        pattern_type=type,
        min_success_rate=min_success_rate,
        limit=limit,
    )
    return [SuggestedPattern(**p) for p in patterns]
