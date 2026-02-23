"""Agent Hub proxy API.

Proxies requests to Agent Hub with proper client authentication.
Frontend calls /api/agent-hub/* which forwards to Agent Hub backend
with X-Client-Id and X-Request-Source headers injected.

This avoids CORS issues and keeps credentials server-side.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services._agent_hub_config import (
    AGENT_HUB_URL,
    SUMMITFLOW_CLIENT_ID,
    SUMMITFLOW_REQUEST_SOURCE,
)

router = APIRouter()


def _auth_headers() -> dict[str, str]:
    """Build authentication headers for Agent Hub requests."""
    headers: dict[str, str] = {}
    if SUMMITFLOW_CLIENT_ID:
        headers["X-Client-Id"] = SUMMITFLOW_CLIENT_ID
    headers["X-Request-Source"] = SUMMITFLOW_REQUEST_SOURCE or "summitflow-frontend"
    return headers


# ---------------------------------------------------------------------------
# Agents (existing endpoint)
# ---------------------------------------------------------------------------


class CodingAgentResponse(BaseModel):
    """Response model for a coding agent."""

    slug: str
    name: str
    description: str | None = None
    is_coding_agent: bool = True


class CodingAgentsListResponse(BaseModel):
    """Response model for list of coding agents."""

    agents: list[CodingAgentResponse]


@router.get("/agent-hub/agents", response_model=CodingAgentsListResponse)
async def list_coding_agents(
    is_coding_agent: bool = True,
) -> CodingAgentsListResponse:
    """Proxy to Agent Hub to list coding agents."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{AGENT_HUB_URL}/api/agents",
                params={"is_coding_agent": str(is_coding_agent).lower()},
                headers=_auth_headers(),
            )
            response.raise_for_status()
            data = response.json()
            return CodingAgentsListResponse(
                agents=[
                    CodingAgentResponse(
                        slug=agent["slug"],
                        name=agent["name"],
                        description=agent.get("description"),
                        is_coding_agent=agent.get("is_coding_agent", True),
                    )
                    for agent in data.get("agents", [])
                ]
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent Hub error: {e.response.text}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to Agent Hub: {e!s}",
            ) from e


# ---------------------------------------------------------------------------
# Models (read-only metadata)
# ---------------------------------------------------------------------------


@router.get("/agent-hub/models")
async def list_models() -> Any:
    """Proxy to Agent Hub to list available models."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{AGENT_HUB_URL}/api/models",
                headers=_auth_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent Hub error: {e.response.text}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to Agent Hub: {e!s}",
            ) from e


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


@router.get("/agent-hub/preferences")
async def get_preferences() -> Any:
    """Proxy to Agent Hub to get user preferences."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{AGENT_HUB_URL}/api/preferences",
                headers=_auth_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent Hub error: {e.response.text}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to Agent Hub: {e!s}",
            ) from e


@router.put("/agent-hub/preferences")
async def update_preferences(request: Request) -> Any:
    """Proxy to Agent Hub to update user preferences."""
    body = await request.json()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.put(
                f"{AGENT_HUB_URL}/api/preferences",
                json=body,
                headers=_auth_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent Hub error: {e.response.text}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to Agent Hub: {e!s}",
            ) from e


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get("/agent-hub/sessions/{session_id}")
async def get_session(session_id: str) -> Any:
    """Proxy to Agent Hub to get session data."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{AGENT_HUB_URL}/api/sessions/{session_id}",
                headers=_auth_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Agent Hub error: {e.response.text}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Could not connect to Agent Hub: {e!s}",
            ) from e


# ---------------------------------------------------------------------------
# Complete (streaming SSE proxy)
# ---------------------------------------------------------------------------


async def _stream_response(response: httpx.Response) -> AsyncIterator[bytes]:
    """Stream response bytes from httpx response."""
    async for chunk in response.aiter_bytes():
        yield chunk


@router.post("/agent-hub/complete")
async def proxy_complete(request: Request) -> StreamingResponse:
    """Proxy streaming completion request to Agent Hub.

    Forwards the request body and streams the SSE response back.
    """
    body = await request.json()
    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))

    try:
        response = await client.send(
            client.build_request(
                "POST",
                f"{AGENT_HUB_URL}/api/complete",
                json=body,
                headers={
                    **_auth_headers(),
                    "Accept": "text/event-stream",
                },
            ),
            stream=True,
        )

        if response.status_code != 200:
            content = await response.aread()
            await response.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=response.status_code,
                detail=content.decode("utf-8", errors="replace"),
            )

        async def stream_and_close() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_and_close(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except httpx.RequestError as e:
        await client.aclose()
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to Agent Hub: {e!s}",
        ) from e
