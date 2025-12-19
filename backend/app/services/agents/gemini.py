"""Gemini client using the official Google GenAI SDK.

Uses native Python integration with google-genai.
Authentication via GOOGLE_API_KEY or GEMINI_API_KEY.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    """Gemini client using the Google Agent Development Kit.

    Uses native Python integration with proper tool support and streaming.

    To set up:
    1. Set GOOGLE_API_KEY environment variable, OR
    2. Run `gcloud auth application-default login`

    Models:
        - "gemini-2.0-flash" (default): Latest fast model
        - "gemini-2.5-pro": Most capable
        - "gemini-2.5-flash": Fast and capable
        - "gemini-1.5-pro": Previous generation
    """

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        """Initialize Gemini ADK client.

        Args:
            model: Model to use
        """
        self.model = model
        self._has_credentials = self._check_credentials()
        logger.info(f"Gemini ADK client initialized (model={model})")

    def _check_credentials(self) -> bool:
        """Check if Gemini credentials are available."""
        # Check for API keys (multiple possible names)
        if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            return True
        # Check ~/.gemini/.env for GEMINI_API_KEY
        gemini_env = os.path.expanduser("~/.gemini/.env")
        if os.path.exists(gemini_env):
            with open(gemini_env) as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        key = line.strip().split("=", 1)[1]
                        os.environ["GOOGLE_API_KEY"] = key  # ADK uses this
                        return True
        # Check for application default credentials
        try:
            import google.auth
            google.auth.default()
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        """Check if Gemini is available."""
        return self._has_credentials

    def get_model_name(self) -> str:
        """Get model name."""
        return self.model

    def authenticate(self) -> bool:
        """Verify Gemini authentication is working."""
        if not self.is_available():
            return False

        try:
            response = self.generate("Say 'ok' and nothing else")
            return "ok" in response.content.lower()
        except Exception as e:
            logger.error(f"Gemini auth test failed: {e}")
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
        """Generate using Gemini ADK.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            working_dir: Working directory (for future tool use)
            **kwargs: Additional options

        Returns:
            LLMResponse with Gemini's response
        """
        import time
        from google import genai

        start_time = time.time()

        client = genai.Client()

        content_parts = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        try:
            # Simple generation without agent framework
            full_prompt = prompt
            if system:
                full_prompt = f"{system}\n\n{prompt}"

            response = client.models.generate_content(
                model=self.model,
                contents=full_prompt,
            )

            # Extract content
            if response.text:
                content_parts.append(response.text)

            # Extract usage if available
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                meta = response.usage_metadata
                usage["prompt_tokens"] = getattr(meta, "prompt_token_count", 0)
                usage["completion_tokens"] = getattr(meta, "candidates_token_count", 0)
                usage["total_tokens"] = getattr(meta, "total_token_count", 0)

            duration_ms = int((time.time() - start_time) * 1000)
            content = "".join(content_parts)

            logger.info(
                f"Gemini response: {duration_ms}ms, "
                f"{usage.get('total_tokens', 0)} tokens, {len(content)} chars"
            )

            return LLMResponse(
                content=content,
                provider="gemini",
                model=self.model,
                usage=usage,
                stop_reason="end_turn",
            )

        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise RuntimeError(f"Gemini error: {e}")
