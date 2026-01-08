"""Agent services for SummitFlow.

MIGRATED TO AGENT HUB: All LLM requests now go through Agent Hub service.
Native Claude/Gemini clients have been removed.

Re-exports from agent_hub_client for backwards compatibility.
"""

from __future__ import annotations

# Re-export everything from agent_hub_client for backwards compatibility
from ..agent_hub_client import (
    AgentHubLLMClient,
    AgentType,
    get_agent,
)
from .base import LLMClient, LLMResponse

__all__ = [
    "AgentHubLLMClient",
    "AgentType",
    "LLMClient",
    "LLMResponse",
    "get_agent",
]
