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
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services._agent_hub_config import (
    AGENT_HUB_URL,
    build_agent_hub_headers,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_REQUEST_SOURCE = "summitflow-frontend"
_MEDIA_TYPE_SSE = "text/event-stream"
_ENCODING_UTF8 = "utf-8"

_SSE_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

_TIMEOUT_DEFAULT = 10.0
_TIMEOUT_STREAM = httpx.Timeout(600.0, connect=10.0)

_ERR_AGENT_HUB = "Agent Hub error: {detail}"
_ERR_CONNECT = "Could not connect to Agent Hub: {detail}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    """Build authentication headers for Agent Hub requests."""
    return build_agent_hub_headers(default_request_source=_DEFAULT_REQUEST_SOURCE)


def _raise_from_status_error(exc: httpx.HTTPStatusError) -> None:
    """Raise HTTPException from an httpx HTTPStatusError."""
    raise HTTPException(
        status_code=exc.response.status_code,
        detail=_ERR_AGENT_HUB.format(detail=exc.response.text),
    ) from exc


def _raise_from_request_error(exc: httpx.RequestError) -> None:
    """Raise HTTPException from an httpx RequestError."""
    raise HTTPException(
        status_code=503,
        detail=_ERR_CONNECT.format(detail=str(exc)),
    ) from exc


async def _get_json(url: str, **kwargs: object) -> object:
    """Perform a GET request and return parsed JSON, raising HTTPException on error."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_DEFAULT) as client:
        try:
            response = await client.get(url, headers=_auth_headers(), **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            _raise_from_status_error(exc)
        except httpx.RequestError as exc:
            _raise_from_request_error(exc)
    return None  # pragma: no cover — unreachable, exceptions always raised above


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


def _parse_agents(data: object) -> CodingAgentsListResponse:
    """Parse raw Agent Hub response data into CodingAgentsListResponse."""
    raw: list[dict[str, Any]] = []
    if isinstance(data, dict):
        raw = data.get("agents", [])
    return CodingAgentsListResponse(
        agents=[
            CodingAgentResponse(
                slug=agent["slug"],
                name=agent["name"],
                description=agent.get("description"),
                is_coding_agent=agent.get("is_coding_agent", True),
            )
            for agent in raw
        ]
    )


@router.get("/agent-hub/agents", response_model=CodingAgentsListResponse)
async def list_coding_agents(
    is_coding_agent: bool = True,
) -> CodingAgentsListResponse:
    """Proxy to Agent Hub to list coding agents."""
    data = await _get_json(
        f"{AGENT_HUB_URL}/api/agents",
        params={"is_coding_agent": str(is_coding_agent).lower()},
    )
    return _parse_agents(data)


# ---------------------------------------------------------------------------
# Models (read-only metadata)
# ---------------------------------------------------------------------------


@router.get("/agent-hub/models")
async def list_models() -> object:
    """Proxy to Agent Hub to list available models."""
    return await _get_json(f"{AGENT_HUB_URL}/api/models")


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


@router.get("/agent-hub/preferences")
async def get_preferences() -> object:
    """Proxy to Agent Hub to get user preferences."""
    return await _get_json(f"{AGENT_HUB_URL}/api/preferences")


@router.put("/agent-hub/preferences")
async def update_preferences(request: Request) -> object:
    """Proxy to Agent Hub to update user preferences."""
    body = await request.json()
    async with httpx.AsyncClient(timeout=_TIMEOUT_DEFAULT) as client:
        try:
            response = await client.put(
                f"{AGENT_HUB_URL}/api/preferences",
                json=body,
                headers=_auth_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            _raise_from_status_error(exc)
        except httpx.RequestError as exc:
            _raise_from_request_error(exc)
    return None  # pragma: no cover — unreachable, exceptions always raised above


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get("/agent-hub/sessions", name="agent_hub_list_sessions")
async def list_agent_hub_sessions(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    agent_slug: str | None = Query(default=None),
    parent_session_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> object:
    """Proxy to Agent Hub to list sessions with filtering."""
    params: dict[str, object] = {
        "page": page,
        "page_size": page_size,
    }
    if project_id:
        params["project_id"] = project_id
    if status:
        params["status"] = status
    if agent_slug:
        params["agent_slug"] = agent_slug
    if parent_session_id:
        params["parent_session_id"] = parent_session_id
    return await _get_json(f"{AGENT_HUB_URL}/api/sessions", params=params)


@router.get("/agent-hub/sessions/{session_id}")
async def get_session(session_id: str) -> object:
    """Proxy to Agent Hub to get session data."""
    return await _get_json(f"{AGENT_HUB_URL}/api/sessions/{session_id}")


@router.post("/agent-hub/sessions/{session_id}/close")
async def close_session(session_id: str) -> object:
    """Proxy to Agent Hub to close a session."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_DEFAULT) as client:
        try:
            response = await client.post(
                f"{AGENT_HUB_URL}/api/sessions/{session_id}/close",
                headers=_auth_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            _raise_from_status_error(exc)
        except httpx.RequestError as exc:
            _raise_from_request_error(exc)
    return None  # pragma: no cover — unreachable


@router.get("/agent-hub/ownership/projects/{project_id}/live")
async def get_project_live_ownership(project_id: str) -> object:
    """Proxy to Agent Hub live ownership inventory for a project."""
    return await _get_json(f"{AGENT_HUB_URL}/api/ownership/projects/{project_id}/live")


# ---------------------------------------------------------------------------
# Complete (streaming SSE proxy)
# ---------------------------------------------------------------------------


async def _stream_and_close(
    response: httpx.Response,
    client: httpx.AsyncClient,
) -> AsyncIterator[bytes]:
    """Stream response bytes then close response and client."""
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()
        await client.aclose()


async def _handle_non_ok_stream(
    response: httpx.Response,
    client: httpx.AsyncClient,
) -> None:
    """Read error body, close resources, and raise HTTPException."""
    content = await response.aread()
    await response.aclose()
    await client.aclose()
    raise HTTPException(
        status_code=response.status_code,
        detail=content.decode(_ENCODING_UTF8, errors="replace"),
    )


def _build_stream_request(client: httpx.AsyncClient, body: object) -> httpx.Request:
    """Build the streaming POST request to Agent Hub /api/complete."""
    return client.build_request(
        "POST",
        f"{AGENT_HUB_URL}/api/complete",
        json=body,
        headers={**_auth_headers(), "Accept": _MEDIA_TYPE_SSE},
    )


@router.post("/agent-hub/complete")
async def proxy_complete(request: Request) -> StreamingResponse:
    """Proxy streaming completion request to Agent Hub.

    Forwards the request body and streams the SSE response back.
    """
    body = await request.json()
    client = httpx.AsyncClient(timeout=_TIMEOUT_STREAM)

    try:
        response = await client.send(_build_stream_request(client, body), stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=503,
            detail=_ERR_CONNECT.format(detail=str(exc)),
        ) from exc

    if response.status_code != 200:
        await _handle_non_ok_stream(response, client)

    return StreamingResponse(
        _stream_and_close(response, client),
        media_type=_MEDIA_TYPE_SSE,
        headers=_SSE_RESPONSE_HEADERS,
    )
