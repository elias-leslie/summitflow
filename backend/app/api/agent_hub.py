"""Agent Hub proxy API.

Proxies requests to Agent Hub to avoid CORS issues from the frontend.
Frontend calls /api/agent-hub/* which forwards to Agent Hub backend.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

AGENT_HUB_URL = os.environ.get("AGENT_HUB_URL", "http://localhost:8003")


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
    """Proxy to Agent Hub to list coding agents.

    Filters to is_coding_agent=true by default to get agents that can execute tasks.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{AGENT_HUB_URL}/api/agents",
                params={"is_coding_agent": str(is_coding_agent).lower()},
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
