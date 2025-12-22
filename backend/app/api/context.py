"""Context API - Progressive disclosure endpoints for token-efficient context loading.

This module provides REST API endpoints for the context system:
- GET /projects/{project_id}/context/index - Get compact context index (~500 tokens)
- POST /projects/{project_id}/context/expand - Expand specific entity for full content
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.memory import ContextBuilder

router = APIRouter()


class ExpandRequest(BaseModel):
    """Request model for entity expansion."""

    entity_id: str  # Format: "type:uuid" (e.g., "obs:abc-123")


class ExpandResponse(BaseModel):
    """Response model for entity expansion."""

    entity_id: str
    type: str
    content: dict[str, Any]
    token_count: int


class ContextIndexResponse(BaseModel):
    """Response model for context index."""

    project_id: str
    session_id: str | None
    items: list[dict[str, Any]]
    item_count: int
    index_tokens: int
    full_tokens: int
    reduction_pct: float
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
    """Get a compact context index (~500 tokens target).

    Returns a summary of available context. Each item includes:
    - id: Entity ID for expand_entity()
    - type: Entity type (observation, checkpoint, pattern)
    - title/summary: Brief description
    - token_estimate: Tokens if expanded

    Use this to decide what context to load, then call /expand for full content.
    """
    builder = ContextBuilder(project_id=project_id, session_id=session_id)

    index = builder.build_index(
        limit=limit,
        include_observations=include_observations,
        include_checkpoints=include_checkpoints,
        include_patterns=include_patterns,
    )

    return ContextIndexResponse(**index)


@router.post("/{project_id}/context/expand", response_model=ExpandResponse)
async def expand_entity(
    project_id: str,
    request: ExpandRequest,
) -> ExpandResponse:
    """Expand an entity from the context index to get full content.

    Accepts entity_id in format "type:uuid":
    - obs:abc-123 - Observation
    - cp:xyz-456 - Checkpoint
    - pat:def-789 - Pattern

    Returns the full content and token count for the entity.
    For patterns, this also increments the usage_count.
    """
    builder = ContextBuilder(project_id=project_id)

    try:
        result = builder.expand_entity(request.entity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ExpandResponse(**result)
