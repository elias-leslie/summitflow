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
from typing import TYPE_CHECKING, Any, Literal

from agent_hub import AgentHubClient, CompletionResponse
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
        max_tokens: int = 4096,
        temperature: float = 1.0,
        purpose: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            purpose: Purpose of this request for session tracking
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

AgentType = Literal["claude", "gemini"]


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
        model: str,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        project_id: str = "summitflow",
    ) -> None:
        """Initialize Agent Hub client.

        Args:
            model: Model identifier (e.g., "claude-sonnet-4-5")
            provider: Optional provider override (auto-detected from model)
            base_url: Agent Hub URL (defaults to AGENT_HUB_URL)
            api_key: Optional API key (defaults to AGENT_HUB_API_KEY)
            project_id: Project ID for session tracking
        """
        self.model = model
        self.provider = provider or self._detect_provider(model)
        self.base_url = base_url or AGENT_HUB_URL
        self.api_key = api_key or AGENT_HUB_API_KEY
        self.project_id = project_id
        self._client: AgentHubClient | None = None

    def _detect_provider(self, model: str) -> str:
        """Detect provider from model name."""
        if "claude" in model.lower():
            return "claude"
        elif "gemini" in model.lower():
            return "gemini"
        else:
            # Default to Claude
            return "claude"

    def _get_client(self) -> AgentHubClient:
        """Get or create Agent Hub client."""
        if self._client is None:
            self._client = AgentHubClient(
                base_url=self.base_url,
                api_key=self.api_key,
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
        """Get the model identifier."""
        return self.model

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        purpose: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion via Agent Hub.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            purpose: Purpose of this request (task_enrichment, code_generation, etc.)
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

        try:
            response = client.complete(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                project_id=self.project_id,
                session_id=kwargs.get("session_id"),
                purpose=purpose,
                enable_caching=kwargs.get("enable_caching", True),
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


def get_agent(
    agent_type: AgentType,
    model: str | None = None,
) -> AgentHubLLMClient:
    """Get an Agent Hub client by type.

    Args:
        agent_type: Either "claude" or "gemini"
        model: Optional model override

    Returns:
        Configured AgentHubLLMClient instance
    """
    from ..constants import DEFAULT_CLAUDE_MODEL, DEFAULT_GEMINI_MODEL

    if agent_type == "claude":
        return AgentHubLLMClient(
            model=model or DEFAULT_CLAUDE_MODEL,
            provider="claude",
        )
    elif agent_type == "gemini":
        return AgentHubLLMClient(
            model=model or DEFAULT_GEMINI_MODEL,
            provider="gemini",
        )
    else:
        raise ValueError(f"Unknown agent type: {agent_type}. Use 'claude' or 'gemini'.")


class DualProviderClient(LLMClient):
    """Single provider client using Agent Hub.

    DEPRECATED: Named 'DualProviderClient' for backwards compatibility only.
    Fallback logic has been removed - uses primary provider only via Agent Hub.
    For new code, use AgentHubLLMClient directly.
    """

    def __init__(
        self,
        primary: AgentType = "gemini",
        claude_model: str | None = None,
        gemini_model: str | None = None,
    ) -> None:
        """Initialize client with primary provider.

        Args:
            primary: Which provider to use ("claude" or "gemini")
            claude_model: Model for Claude (used if primary="claude")
            gemini_model: Model for Gemini (used if primary="gemini")
        """
        from ..constants import DEFAULT_CLAUDE_MODEL, DEFAULT_GEMINI_MODEL

        self.primary = primary
        if primary == "claude":
            self._model = claude_model or DEFAULT_CLAUDE_MODEL
        else:
            self._model = gemini_model or DEFAULT_GEMINI_MODEL

        self._client: AgentHubLLMClient | None = None

    def _ensure_initialized(self) -> None:
        """Initialize client on first use."""
        if self._client is not None:
            return

        self._client = AgentHubLLMClient(
            model=self._model,
            provider=self.primary,
        )

    def is_available(self) -> bool:
        """Check if provider is available."""
        try:
            self._ensure_initialized()
            return self._client.is_available() if self._client else False
        except Exception:
            return False

    def get_model_name(self) -> str:
        """Get the model identifier."""
        self._ensure_initialized()
        return self._client.get_model_name() if self._client else self._model

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        purpose: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate using primary provider via Agent Hub.

        No fallback - if primary fails, error is raised.
        """
        self._ensure_initialized()
        if not self._client:
            raise RuntimeError("Client not initialized")

        return self._client.generate(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            purpose=purpose,
            **kwargs,
        )

    def close(self) -> None:
        """Close the client connection."""
        if self._client:
            self._client.close()
            self._client = None


__all__ = [
    "AgentHubLLMClient",
    "AgentType",
    "DualProviderClient",
    "LLMClient",
    "LLMResponse",
    "get_agent",
]
