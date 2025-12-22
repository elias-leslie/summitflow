"""Observations API - Observation capture and retrieval.

This module provides REST API endpoints for the observation system:
- POST /projects/{project_id}/observations/capture - Fire-and-forget capture
- GET /projects/{project_id}/observations - List observations with filters
- GET /projects/{project_id}/observations/search - Full-text search
- GET /projects/{project_id}/observations/stream - SSE stream (task 2.5)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.memory import ObservationQueue
from ..storage import memory as memory_storage

router = APIRouter()

# Redis for SSE pub/sub
REDIS_URL = "redis://localhost:6379/1"


# Pydantic models
class CaptureRequest(BaseModel):
    """Request model for observation capture."""

    session_id: str
    agent_type: str  # 'claude-code', 'claude', 'gemini'
    tool_name: str
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None


class CaptureResponse(BaseModel):
    """Response model for observation capture."""

    queued: bool
    queue_item_id: str


@router.post("/{project_id}/observations/capture", response_model=CaptureResponse)
async def capture_observation(
    project_id: str,
    request: CaptureRequest,
) -> CaptureResponse:
    """Fire-and-forget capture of a tool execution.

    Enqueues the tool execution for async observation extraction.
    Returns 202 Accepted immediately with queue item ID.

    Target latency: <100ms
    """
    queue = ObservationQueue()

    item = await queue.enqueue(
        project_id=project_id,
        session_id=request.session_id,
        agent_type=request.agent_type,
        tool_name=request.tool_name,
        tool_input=request.tool_input,
        tool_output=request.tool_output,
    )

    return CaptureResponse(queued=True, queue_item_id=item["id"])


@router.get("/{project_id}/observations")
async def list_project_observations(
    project_id: str,
    agent_type: str | None = Query(None, description="Filter by agent type"),
    observation_type: str | None = Query(None, description="Filter by observation type"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List observations for a specific project.

    Returns observations sorted by created_at descending (newest first).
    """
    return memory_storage.list_observations(
        project_id=project_id,
        agent_type=agent_type,
        observation_type=observation_type,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}/observations/search")
async def search_observations(
    project_id: str,
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Full-text search observations.

    Uses PostgreSQL FTS on title, subtitle, and narrative fields.
    Results ranked by relevance.
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="Search query required")

    return memory_storage.search_observations_fts(
        project_id=project_id,
        query=q,
        limit=limit,
    )


@router.get("/{project_id}/observations/{observation_id}")
async def get_observation(
    project_id: str,
    observation_id: str,
) -> dict[str, Any]:
    """Get a single observation by ID."""
    observation = memory_storage.get_observation(observation_id)

    if not observation:
        raise HTTPException(status_code=404, detail="Observation not found")

    if observation["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Observation not found")

    return observation


# SSE stream endpoint (task 2.5)
@router.get("/{project_id}/observations/stream")
async def stream_observations(
    project_id: str,
    request: Request,
) -> StreamingResponse:
    """Server-Sent Events stream for real-time observations.

    Subscribes to Redis pub/sub and forwards observation events.
    Sends heartbeat every 30 seconds to keep connection alive.
    """

    async def event_generator():
        """Generate SSE events from Redis pub/sub."""
        r = redis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        channel = f"observations:{project_id}"
        pubsub.subscribe(channel)

        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'channel': channel})}\n\n"

            heartbeat_interval = 30  # seconds
            last_heartbeat = asyncio.get_event_loop().time()

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Get message with timeout for heartbeat
                message = pubsub.get_message(timeout=1.0)

                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    # Parse the message to extract event type
                    try:
                        parsed = json.loads(data)
                        event_type = parsed.get("event", "observation")
                        event_data = json.dumps(parsed.get("data", parsed))
                        yield f"event: {event_type}\ndata: {event_data}\n\n"
                    except json.JSONDecodeError:
                        yield f"data: {data}\n\n"

                # Send heartbeat if needed
                current_time = asyncio.get_event_loop().time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    yield f"event: heartbeat\ndata: {json.dumps({'time': current_time})}\n\n"
                    last_heartbeat = current_time

                # Small delay to prevent CPU spinning
                await asyncio.sleep(0.1)

        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
