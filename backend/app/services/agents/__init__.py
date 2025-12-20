"""Agent services for SummitFlow.

Provides unified interface to LLM providers (Claude, Gemini).
Both use CLI tools with cached credentials - no API keys needed.
"""

from __future__ import annotations

import logging
from typing import Literal

from .base import LLMClient, LLMResponse
from .claude import ClaudeClient
from .gemini import GeminiClient

logger = logging.getLogger(__name__)

AgentType = Literal["claude", "gemini"]


def get_agent(
    agent_type: AgentType,
    model: str | None = None,
) -> LLMClient:
    """Get an agent client by type.

    Args:
        agent_type: Either "claude" or "gemini"
        model: Optional model override (uses default if not specified)

    Returns:
        Configured LLMClient instance

    Raises:
        ValueError: If agent_type is invalid
        RuntimeError: If CLI for agent is not available
    """
    if agent_type == "claude":
        return ClaudeClient(model=model or "claude-sonnet-4-5")
    elif agent_type == "gemini":
        return GeminiClient(model=model or "gemini-3-flash-preview")
    else:
        raise ValueError(f"Unknown agent type: {agent_type}. Use 'claude' or 'gemini'.")


class DualProviderClient(LLMClient):
    """Dual provider client with automatic failover.

    Tries primary provider first, falls back to secondary on error.
    Useful for reliability and cost optimization.
    """

    def __init__(
        self,
        primary: AgentType = "gemini",
        claude_model: str = "claude-sonnet-4-5",
        gemini_model: str = "gemini-3-flash-preview",
    ) -> None:
        """Initialize dual provider client.

        Args:
            primary: Which provider to try first ("claude" or "gemini")
            claude_model: Model for Claude
            gemini_model: Model for Gemini
        """
        self.primary = primary
        self.providers: dict[str, LLMClient] = {}

        # Initialize providers lazily to handle missing CLIs gracefully
        self._claude_model = claude_model
        self._gemini_model = gemini_model
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Initialize providers on first use."""
        if self._initialized:
            return

        try:
            self.providers["claude"] = ClaudeClient(model=self._claude_model)
        except RuntimeError as e:
            logger.warning(f"Claude not available: {e}")

        try:
            self.providers["gemini"] = GeminiClient(model=self._gemini_model)
        except RuntimeError as e:
            logger.warning(f"Gemini not available: {e}")

        if not self.providers:
            raise RuntimeError("No LLM providers available")

        self._initialized = True

    def is_available(self) -> bool:
        """Check if at least one provider is available."""
        try:
            self._ensure_initialized()
            return any(p.is_available() for p in self.providers.values())
        except RuntimeError:
            return False

    def get_model_name(self) -> str:
        """Get model name of primary provider."""
        self._ensure_initialized()
        if self.primary in self.providers:
            return self.providers[self.primary].get_model_name()
        # Fall back to any available
        return next(iter(self.providers.values())).get_model_name()

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        """Generate with automatic failover.

        Tries primary provider first, falls back to secondary on error.
        """
        self._ensure_initialized()

        # Determine order
        secondary = "gemini" if self.primary == "claude" else "claude"
        order = [self.primary, secondary]

        last_error = None
        for provider_name in order:
            if provider_name not in self.providers:
                continue

            provider = self.providers[provider_name]
            try:
                return provider.generate(
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
            except Exception as e:
                logger.warning(f"{provider_name} failed: {e}, trying fallback...")
                last_error = e
                continue

        raise RuntimeError(f"All providers failed. Last error: {last_error}")


__all__ = [
    "LLMClient",
    "LLMResponse",
    "ClaudeClient",
    "GeminiClient",
    "DualProviderClient",
    "get_agent",
    "AgentType",
]
