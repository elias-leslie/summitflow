"""Agent Hub client wrapper for SummitFlow.

Provides LLMClient-compatible interface using Agent Hub API.
This replaces the direct Claude/Gemini clients with centralized Agent Hub.

This module provides:
- LLMResponse: Standardized response dataclass
- LLMClient: Abstract base class for LLM providers
- AgentHubLLMClient: Concrete implementation using Agent Hub API
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_hub import AgentHubClient
from agent_hub.exceptions import AgentHubError

from ..logging_config import get_logger
from ._agent_hub_config import (
    AGENT_HUB_API_KEY,
    AGENT_HUB_URL,
    SUMMITFLOW_CLIENT_ID,
    SUMMITFLOW_CLIENT_SECRET,
    SUMMITFLOW_REQUEST_SOURCE,
    get_async_client,
    get_sync_client,
    response_to_llm_response,
)
from ._agent_hub_types import LLMClient, LLMResponse

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


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
            self._client = AgentHubClient(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=600.0,
                client_name="summitflow",
                client_id=SUMMITFLOW_CLIENT_ID,
                client_secret=SUMMITFLOW_CLIENT_SECRET,
                request_source=SUMMITFLOW_REQUEST_SOURCE,
            )
        return self._client

    def is_available(self) -> bool:
        """Check if Agent Hub is available."""
        try:
            client = self._get_client()
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
        tier_preference: str | None = None,
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

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

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
                external_id=task_id,
                enable_caching=kwargs.get("enable_caching", True),
                use_memory=effective_use_memory,
                memory_group_id=effective_memory_group,
                tier_preference=tier_preference,
            )
            return response_to_llm_response(response)
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
    "AGENT_HUB_API_KEY",
    "AGENT_HUB_URL",
    "SUMMITFLOW_CLIENT_ID",
    "SUMMITFLOW_CLIENT_SECRET",
    "SUMMITFLOW_REQUEST_SOURCE",
    "AgentHubLLMClient",
    "LLMClient",
    "LLMResponse",
    "get_agent",
    "get_async_client",
    "get_sync_client",
]
