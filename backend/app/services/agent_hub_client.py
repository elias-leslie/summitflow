"""Agent Hub client wrapper for SummitFlow.

Provides LLMClient-compatible interface using Agent Hub API.
This replaces the direct Claude/Gemini clients with centralized Agent Hub.

This module provides:
- LLMResponse: Standardized response dataclass
- LLMClient: Abstract base class for LLM providers
- AgentHubLLMClient: Concrete implementation using Agent Hub API
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_hub import AgentHubClient, AsyncAgentHubClient, CompletionResponse
from agent_hub.exceptions import AgentHubError

from ..logging_config import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    """Standardized LLM response across all providers."""

    content: str
    provider: str  # 'claude' or 'gemini'
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "end_turn"  # 'end_turn', 'tool_use', 'max_tokens'
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """Abstract base class for LLM providers.

    Implementations route requests through Agent Hub for unified management.
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 1.0,
        purpose: str | None = None,
        task_id: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            temperature: Sampling temperature
            purpose: Purpose of this request for session tracking
            task_id: Task ID for session linkage
            **kwargs: Provider-specific options

        Returns:
            LLMResponse with content and metadata

        Raises:
            RuntimeError: If generation fails
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available and operational."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model identifier used by this client."""
        pass

    def authenticate(self) -> bool:
        """Verify authentication is working."""
        return self.is_available()

    def send_message(
        self,
        message: str,
        system: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a message and get response text.

        Simplified interface for basic chat interactions.
        """
        response = self.generate(prompt=message, system=system, **kwargs)
        return response.content


# Default Agent Hub URL - can be overridden via environment
AGENT_HUB_URL = os.getenv("AGENT_HUB_URL", "http://localhost:8003")
AGENT_HUB_API_KEY = os.getenv("AGENT_HUB_API_KEY")

# SummitFlow client credentials for Agent Hub authentication
SUMMITFLOW_CLIENT_ID = os.getenv("SUMMITFLOW_CLIENT_ID")
SUMMITFLOW_CLIENT_SECRET = os.getenv("SUMMITFLOW_CLIENT_SECRET")
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
        client_secret=SUMMITFLOW_CLIENT_SECRET,
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
        client_secret=SUMMITFLOW_CLIENT_SECRET,
        request_source=SUMMITFLOW_REQUEST_SOURCE,
    )


def _response_to_llm_response(response: CompletionResponse) -> LLMResponse:
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


class AgentHubLLMClient(LLMClient):
    """LLM client that uses Agent Hub API.

    Implements the LLMClient interface but routes all requests
    through Agent Hub for unified provider management.
    """

    def __init__(
        self,
        agent_slug: str,
        project_id: str = "summitflow",
        use_memory: bool = True,
        memory_group_id: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize Agent Hub client.

        Args:
            agent_slug: Agent slug for routing (required). See /api/agents for available agents.
            project_id: Project ID for session tracking
            use_memory: Enable memory injection (mandates, guardrails). Default True.
            memory_group_id: Memory group ID for scoping (e.g., "global", "project:xyz").
            base_url: Agent Hub URL (defaults to AGENT_HUB_URL)
            api_key: Optional API key (defaults to AGENT_HUB_API_KEY)
        """
        if not agent_slug:
            raise ValueError(
                "agent_slug is required. See Agent Hub /api/agents for available agents."
            )

        self.agent_slug = agent_slug
        self.base_url = base_url or AGENT_HUB_URL
        self.api_key = api_key or AGENT_HUB_API_KEY
        self.project_id = project_id
        self.use_memory = use_memory
        self.memory_group_id = memory_group_id
        self._client: AgentHubClient | None = None

    def _get_client(self) -> AgentHubClient:
        """Get or create Agent Hub client."""
        if self._client is None:
            # 10 minute timeout for complex coding tasks
            # Claude CLI can take 5+ minutes for real code generation
            self._client = AgentHubClient(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=600.0,
                client_name="summitflow",  # Usage tracking
                client_id=SUMMITFLOW_CLIENT_ID,
                client_secret=SUMMITFLOW_CLIENT_SECRET,
                request_source=SUMMITFLOW_REQUEST_SOURCE,
            )
        return self._client

    def is_available(self) -> bool:
        """Check if Agent Hub is available."""
        try:
            client = self._get_client()
            # Simple health check - list sessions with minimal params
            client.list_sessions(page_size=1)
            return True
        except Exception as e:
            logger.warning(f"Agent Hub not available: {e}")
            return False

    def get_model_name(self) -> str:
        """Get the model/agent identifier."""
        return f"agent:{self.agent_slug}"

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 1.0,
        purpose: str | None = None,
        task_id: str | None = None,
        use_memory: bool | None = None,
        memory_group_id: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion via Agent Hub.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            temperature: Sampling temperature
            purpose: Purpose of this request (task_enrichment, code_generation, etc.)
            task_id: Task ID for session linkage (stored as external_id in Agent Hub)
            use_memory: Override memory injection setting (defaults to instance setting)
            memory_group_id: Override memory group ID (defaults to instance setting)
            **kwargs: Additional options (session_id, enable_caching, etc.)

        Returns:
            LLMResponse with content and metadata

        Raises:
            RuntimeError: If generation fails
        """
        client = self._get_client()

        # Build messages array
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Use instance defaults if not overridden
        effective_use_memory = use_memory if use_memory is not None else self.use_memory
        effective_memory_group = memory_group_id or self.memory_group_id

        try:
            response = client.complete(
                agent_slug=self.agent_slug,
                messages=messages,
                temperature=temperature,
                project_id=self.project_id,
                session_id=kwargs.get("session_id"),
                purpose=purpose,
                external_id=task_id,  # Link session to task for memory extraction
                enable_caching=kwargs.get("enable_caching", True),
                use_memory=effective_use_memory,
                memory_group_id=effective_memory_group,
            )
            return _response_to_llm_response(response)
        except AgentHubError as e:
            logger.error(f"Agent Hub error: {e}")
            raise RuntimeError(f"Agent Hub request failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise RuntimeError(f"Agent Hub request failed: {e}") from e

    def close(self) -> None:
        """Close the client connection."""
        if self._client:
            self._client.close()
            self._client = None


def get_agent(agent_slug: str) -> AgentHubLLMClient:
    """Get an Agent Hub client for the specified agent.

    Args:
        agent_slug: Agent slug (e.g., "coder", "analyst", "planner", "auditor", "reviewer").
            See Agent Hub /api/agents for available agents.

    Returns:
        Configured AgentHubLLMClient instance
    """
    return AgentHubLLMClient(agent_slug=agent_slug)


__all__ = [
    "AgentHubLLMClient",
    "LLMClient",
    "LLMResponse",
    "get_agent",
    "get_async_client",
    "get_sync_client",
]
