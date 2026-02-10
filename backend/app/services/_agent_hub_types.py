"""Core types and abstract interfaces for Agent Hub LLM integration.

Internal module - import from agent_hub_client instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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


__all__ = ["LLMClient", "LLMResponse"]
