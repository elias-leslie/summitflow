"""API interaction for prompt management."""

from __future__ import annotations

from typing import Any

from .memory_api import agent_hub_request


def prompt_api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    """Make API request to prompt endpoints."""
    return agent_hub_request(method, f"/api/prompts{path}", tool_name="st prompt", **kwargs)
