"""Context API - Legacy endpoints, memory system removed.

Memory functionality moved to Agent Hub with Graphiti knowledge graph.
These endpoints return empty/disabled responses for backward compatibility.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.context_helpers import filter_rules_by_files

logger = logging.getLogger(__name__)

router = APIRouter()


class ExpandRequest(BaseModel):
    """Request model for entity expansion."""

    entity_id: str
    session_id: str | None = None
    task_id: str | None = None


class ExpandResponse(BaseModel):
    """Response model for entity expansion."""

    entity_id: str
    type: str
    content: dict[str, Any]
    token_count: int
    jsonl: str | None = None


class ContextIndexResponse(BaseModel):
    """Response model for context index."""

    project_id: str
    session_id: str | None
    items: list[dict[str, Any]]
    item_count: int
    index_tokens: int
    full_tokens: int
    reduction_pct: float
    from_cache: bool = False
    instructions: str


@router.get("/{project_id}/context/index", response_model=ContextIndexResponse)
async def get_context_index(
    project_id: str,
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(20, ge=1, le=50, description="Max items per category"),
    include_observations: bool = Query(True, description="Include observations"),
    include_checkpoints: bool = Query(True, description="Include checkpoints"),
    include_patterns: bool = Query(True, description="Include applied patterns"),
) -> ContextIndexResponse:
    """Get a compact context index.

    Memory system removed - returns empty index.
    Memory functionality moved to Agent Hub with Graphiti.
    """
    return ContextIndexResponse(
        project_id=project_id,
        session_id=session_id,
        items=[],
        item_count=0,
        index_tokens=0,
        full_tokens=0,
        reduction_pct=0.0,
        from_cache=False,
        instructions="Memory system moved to Agent Hub. Use /api/memory endpoints there.",
    )


@router.post("/{project_id}/context/expand", response_model=ExpandResponse)
async def expand_entity(
    project_id: str,
    request: ExpandRequest,
) -> ExpandResponse:
    """Expand an entity from the context index.

    Memory system removed - returns empty content.
    Memory functionality moved to Agent Hub with Graphiti.
    """
    raise HTTPException(
        status_code=410,
        detail="Memory system removed. Memory functionality moved to Agent Hub.",
    )


class SessionStartRequest(BaseModel):
    """Request model for session-start context injection."""

    current_time: str | None = None
    recent_files: str | None = None
    uncommitted_count: int | None = None
    session_id: str | None = None


class SessionStartContextResponse(BaseModel):
    """Response model for session-start context injection."""

    context_block: str
    token_estimate: int
    items_included: int
    patterns_index: list[dict[str, Any]] = Field(default_factory=list)
    tools_hint: str = "`st ready|update|close`"


@router.post("/{project_id}/context/session-start", response_model=SessionStartContextResponse)
async def get_session_start_context(
    project_id: str,
    request: SessionStartRequest | None = None,
) -> SessionStartContextResponse:
    """Get context for session-start injection.

    Memory system removed - returns empty context.
    Memory functionality moved to Agent Hub with Graphiti.
    """
    return SessionStartContextResponse(
        context_block="",
        token_estimate=0,
        items_included=0,
        patterns_index=[],
    )


class PatternEffectivenessItem(BaseModel):
    """Effectiveness metrics for a single pattern."""

    pattern_id: str
    total_access: int
    success_count: int
    partial_count: int
    failure_count: int
    success_rate: float
    injection_count: int
    api_count: int
    cli_count: int
    unique_sessions: int


class PatternEffectivenessResponse(BaseModel):
    """Response for pattern effectiveness endpoint."""

    project_id: str
    days: int
    patterns: list[PatternEffectivenessItem]
    summary: dict[str, Any]


@router.get("/{project_id}/memory/patterns/effectiveness")
async def get_patterns_effectiveness(
    project_id: str,
    days: int = Query(30, ge=1, le=365, description="Days to analyze"),
) -> PatternEffectivenessResponse:
    """Get pattern effectiveness metrics.

    Memory system removed - returns empty response.
    """
    return PatternEffectivenessResponse(
        project_id=project_id,
        days=days,
        patterns=[],
        summary={},
    )


class AccessSummaryResponse(BaseModel):
    """Response for access summary endpoint."""

    project_id: str
    days: int
    total_access: int
    by_entity_type: dict[str, int]
    by_access_source: dict[str, int]
    by_outcome: dict[str, int]
    unique_sessions: int


@router.get("/{project_id}/memory/access/summary")
async def get_access_statistics(
    project_id: str,
    days: int = Query(7, ge=1, le=365, description="Days to analyze"),
) -> AccessSummaryResponse:
    """Get summary statistics for context access.

    Memory system removed - returns empty response.
    """
    return AccessSummaryResponse(
        project_id=project_id,
        days=days,
        total_access=0,
        by_entity_type={},
        by_access_source={},
        by_outcome={},
        unique_sessions=0,
    )


class TimelineResponse(BaseModel):
    """Response model for timeline/context-around endpoint."""

    anchor: dict[str, Any]
    before: list[dict[str, Any]]
    after: list[dict[str, Any]]
    total_tokens: int


@router.get("/{project_id}/context/timeline", response_model=TimelineResponse)
async def get_context_timeline(
    project_id: str,
    anchor_id: str = Query(..., description="Observation ID to center timeline on"),
    before: int = Query(5, ge=0, le=20, description="Number of items before anchor"),
    after: int = Query(5, ge=0, le=20, description="Number of items after anchor"),
) -> TimelineResponse:
    """Get observations around a specific anchor point in time.

    Memory system removed - returns 410 Gone.
    """
    raise HTTPException(
        status_code=410,
        detail="Memory system removed. Memory functionality moved to Agent Hub.",
    )


class TaskContextResponse(BaseModel):
    """Response model for task context."""

    files: list[str]
    rules: list[str]
    rule_contents: dict[str, str]
    patterns: list[dict[str, Any]]
    observations: list[dict[str, Any]]


# Global rules directory
GLOBAL_RULES_DIR = Path("/home/kasadis/.claude/rules")


def _get_project_rules_dir(project_id: str) -> Path | None:
    """Get rules directory for a project."""
    from ..storage.projects import get_project_root_path

    root = get_project_root_path(project_id)
    if root:
        return Path(root) / ".claude" / "rules"
    return None


def _read_rule_file(filename: str, project_id: str | None = None) -> str | None:
    """Read a rule file from project or global rules directory."""
    if project_id:
        project_rules = _get_project_rules_dir(project_id)
        if project_rules:
            project_path = project_rules / filename
            if project_path.exists():
                return project_path.read_text()

    global_path = GLOBAL_RULES_DIR / filename
    if global_path.exists():
        return global_path.read_text()

    return None


@router.get("/{project_id}/context/for-task", response_model=TaskContextResponse)
async def get_context_for_task(
    project_id: str,
    files: str = Query(..., description="Comma-separated list of file paths affected by the task"),
) -> TaskContextResponse:
    """Get context relevant to a specific task based on files it affects.

    Returns rules based on files. Patterns and observations no longer available
    (memory system moved to Agent Hub).
    """
    file_list = [f.strip() for f in files.split(",") if f.strip()]

    if not file_list:
        raise HTTPException(status_code=400, detail="No files provided")

    rule_names = filter_rules_by_files(file_list)

    rule_contents: dict[str, str] = {}
    for rule in rule_names:
        content = _read_rule_file(rule, project_id)
        if content:
            rule_contents[rule] = content

    return TaskContextResponse(
        files=file_list,
        rules=rule_names,
        rule_contents=rule_contents,
        patterns=[],  # Memory system removed
        observations=[],  # Memory system removed
    )
