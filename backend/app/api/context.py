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
from ..storage.agent_configs import is_memory_feature_enabled

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


class SessionStartContextResponse(BaseModel):
    """Response model for session-start context injection."""

    context_block: str
    token_estimate: int
    items_included: int


@router.get("/{project_id}/context/session-start", response_model=SessionStartContextResponse)
async def get_session_start_context(
    project_id: str,
    limit: int = Query(10, ge=1, le=20, description="Max items to include"),
) -> SessionStartContextResponse:
    """Get context for automatic session-start injection.

    Called by SessionStart hook to inject recent context at the start
    of new Claude Code sessions. Returns empty block if context injection
    is disabled for the project.

    Returns:
        context_block: Plain text formatted for injection
        token_estimate: Estimated tokens in the block
        items_included: Number of items included
    """
    # Check if context injection is enabled for this project
    if not is_memory_feature_enabled(project_id, "context_injection"):
        return SessionStartContextResponse(
            context_block="",
            token_estimate=0,
            items_included=0,
        )

    builder = ContextBuilder(project_id=project_id)
    index = builder.build_index(
        limit=limit,
        include_observations=True,
        include_checkpoints=True,
        include_patterns=True,
    )

    # Return empty if no items
    if not index.get("items"):
        return SessionStartContextResponse(
            context_block="",
            token_estimate=0,
            items_included=0,
        )

    # Format as plain text for injection
    lines = ["## Recent Project Context", ""]
    for item in index["items"]:
        item_type = item.get("type", "unknown")
        title = item.get("title", item.get("summary", "No title"))
        created = item.get("created_at", "")[:10] if item.get("created_at") else ""

        if item_type == "observation":
            obs_type = item.get("observation_type", "general")
            lines.append(f"- [{obs_type}] {title} ({created})")
        elif item_type == "checkpoint":
            lines.append(f"- [checkpoint] {title} ({created})")
        elif item_type == "pattern":
            lines.append(f"- [pattern] {title}")
        else:
            lines.append(f"- {title}")

    lines.append("")
    lines.append("Use /projects/{project_id}/context/expand for full details.")

    context_block = "\n".join(lines)
    token_estimate = len(context_block) // 4  # Rough estimate

    return SessionStartContextResponse(
        context_block=context_block,
        token_estimate=token_estimate,
        items_included=len(index["items"]),
    )
