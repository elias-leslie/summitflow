"""API interaction for agent management."""

from __future__ import annotations

from typing import Any

from .memory_api import agent_hub_request


def agents_api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    """Make an Agent Hub agent-management request."""
    return agent_hub_request(method, f"/api/agents{path}", tool_name="st agents", **kwargs)
