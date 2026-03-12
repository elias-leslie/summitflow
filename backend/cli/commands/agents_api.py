"""API interaction for agent management."""

from __future__ import annotations

from typing import Any

from .memory_api import agent_hub_request


def agents_api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    """Make an Agent Hub agent-management request."""
    return agent_hub_request(method, f"/api/agents{path}", tool_name="st agents", **kwargs)


def agent_preview_api(slug: str, **kwargs: Any) -> dict[str, Any]:
    """Fetch runtime preview for an agent."""
    params = {
        key: value
        for key, value in kwargs.items()
        if value is not None
    }
    return agent_hub_request(
        "GET",
        f"/api/agents/{slug}/preview",
        tool_name="st agents",
        params=params,
    )
