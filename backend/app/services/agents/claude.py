"""Claude client using the official Claude Agent SDK.

Uses the same infrastructure that powers Claude Code.
No API keys needed - uses OAuth via cached credentials.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class ClaudeClient(LLMClient):
    """Claude client using the official Agent SDK.

    Uses ClaudeSDKClient for proper streaming, session management,
    and all Claude Code features.

    To set up:
    1. Install Claude Code CLI
    2. Run `claude` once to authenticate via browser
    3. Credentials are cached locally (~/.claude/)

    Models:
        - "sonnet" (default): Claude 3.5 Sonnet - fast and capable
        - "opus": Claude 3 Opus - most capable
        - "haiku": Claude 3 Haiku - fastest
    """

    def __init__(self, model: str = "sonnet") -> None:
        """Initialize Claude SDK client.

        Args:
            model: Model to use ("sonnet", "opus", "haiku")
        """
        self.model = model
        self._cli_path = shutil.which("claude")
        if not self._cli_path:
            raise RuntimeError(
                "Claude CLI not found in PATH. "
                "Install with: npm install -g @anthropic-ai/claude-code"
            )
        logger.info(f"Claude SDK client initialized (model={model})")

    def is_available(self) -> bool:
        """Check if Claude SDK is available."""
        return self._cli_path is not None

    def get_model_name(self) -> str:
        """Get model name."""
        return f"claude-{self.model}"

    def authenticate(self) -> bool:
        """Verify Claude authentication is working."""
        if not self.is_available():
            return False

        try:
            # Quick test via SDK
            response = self.generate("Say 'ok' and nothing else")
            return "ok" in response.content.lower()
        except Exception as e:
            logger.error(f"Claude auth test failed: {e}")
            return False

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        working_dir: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate using Claude SDK.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            max_tokens: Maximum tokens (SDK manages this)
            temperature: Sampling temperature (SDK manages this)
            working_dir: Working directory for the agent
            **kwargs: Additional options

        Returns:
            LLMResponse with Claude's response
        """
        # Run async code synchronously
        return asyncio.get_event_loop().run_until_complete(
            self._generate_async(prompt, system, working_dir)
        )

    async def _generate_async(
        self,
        prompt: str,
        system: str | None = None,
        working_dir: str | None = None,
    ) -> LLMResponse:
        """Async implementation of generate."""
        import time

        start_time = time.time()

        # Build options
        options = ClaudeAgentOptions(
            cwd=working_dir or ".",
            permission_mode="bypassPermissions",  # For simple queries
            cli_path=self._cli_path,
            model=self.model,
        )

        # Combine system + prompt if system provided
        full_prompt = prompt
        if system:
            full_prompt = f"{system}\n\n{prompt}"

        content_parts = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        try:
            client = ClaudeSDKClient(options=options)
            async with client:
                await client.query(full_prompt)

                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                content_parts.append(block.text)

                    elif isinstance(msg, ResultMessage):
                        # Extract usage from result
                        if hasattr(msg, "total_cost_usd"):
                            # Estimate tokens from cost (rough approximation)
                            pass

            duration_ms = int((time.time() - start_time) * 1000)
            content = "".join(content_parts)

            logger.info(
                f"Claude SDK response: {duration_ms}ms, {len(content)} chars"
            )

            return LLMResponse(
                content=content,
                provider="claude",
                model=self.model,
                usage=usage,
                stop_reason="end_turn",
            )

        except Exception as e:
            logger.error(f"Claude SDK error: {e}")
            raise RuntimeError(f"Claude SDK error: {e}")
