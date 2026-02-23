"""Configuration and client factory functions for Agent Hub.

Internal module - import from agent_hub_client instead.
"""

from __future__ import annotations

import os

from agent_hub import AgentHubClient, AsyncAgentHubClient, CompletionResponse

from ._agent_hub_types import LLMResponse

# Default Agent Hub URL - can be overridden via environment
AGENT_HUB_URL = os.getenv("AGENT_HUB_URL", "http://localhost:8003")
AGENT_HUB_API_KEY = os.getenv("AGENT_HUB_API_KEY")

# SummitFlow client credentials for Agent Hub authentication
SUMMITFLOW_CLIENT_ID = os.getenv("SUMMITFLOW_CLIENT_ID")
SUMMITFLOW_REQUEST_SOURCE = os.getenv("SUMMITFLOW_REQUEST_SOURCE", "summitflow")


def get_sync_client(
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 600.0,
    client_name: str = "summitflow",
) -> AgentHubClient:
    """Get a configured sync Agent Hub client with credentials.

    Args:
        base_url: Agent Hub URL (defaults to AGENT_HUB_URL)
        api_key: Optional API key (defaults to AGENT_HUB_API_KEY)
        timeout: Request timeout in seconds (default: 600)
        client_name: Client identifier for usage tracking

    Returns:
        Configured AgentHubClient with credentials injected
    """
    return AgentHubClient(
        base_url=base_url or AGENT_HUB_URL,
        api_key=api_key or AGENT_HUB_API_KEY,
        timeout=timeout,
        client_name=client_name,
        client_id=SUMMITFLOW_CLIENT_ID,
        request_source=SUMMITFLOW_REQUEST_SOURCE,
    )


def get_async_client(
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 600.0,
    client_name: str = "summitflow",
) -> AsyncAgentHubClient:
    """Get a configured async Agent Hub client with credentials.

    Args:
        base_url: Agent Hub URL (defaults to AGENT_HUB_URL)
        api_key: Optional API key (defaults to AGENT_HUB_API_KEY)
        timeout: Request timeout in seconds (default: 600)
        client_name: Client identifier for usage tracking

    Returns:
        Configured AsyncAgentHubClient with credentials injected
    """
    return AsyncAgentHubClient(
        base_url=base_url or AGENT_HUB_URL,
        api_key=api_key or AGENT_HUB_API_KEY,
        timeout=timeout,
        client_name=client_name,
        client_id=SUMMITFLOW_CLIENT_ID,
        request_source=SUMMITFLOW_REQUEST_SOURCE,
    )


def response_to_llm_response(response: CompletionResponse) -> LLMResponse:
    """Convert Agent Hub response to LLMResponse."""
    return LLMResponse(
        content=response.content,
        provider=response.provider,
        model=response.model,
        usage={
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
        },
        stop_reason=response.finish_reason or "end_turn",
        tool_calls=[],
        raw_response={
            "session_id": response.session_id,
            "from_cache": response.from_cache,
        },
    )


__all__ = [
    "AGENT_HUB_API_KEY",
    "AGENT_HUB_URL",
    "SUMMITFLOW_CLIENT_ID",
    "SUMMITFLOW_REQUEST_SOURCE",
    "get_async_client",
    "get_sync_client",
    "response_to_llm_response",
]
