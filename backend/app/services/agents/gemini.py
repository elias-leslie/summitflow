"""Gemini CLI client for SummitFlow.

Uses the Gemini CLI with cached Google credentials (completely free).
No API keys needed - authentication via Google account.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from typing import Any

from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    """Gemini CLI client.

    Uses local Gemini CLI with cached credentials (completely free).
    Authentication is handled automatically by the CLI via Google OAuth.

    To set up:
    1. Install Gemini CLI
    2. Run `gemini` once to authenticate via Google
    3. Credentials are cached locally

    Models:
        - "gemini-2.5-pro" (default): Most capable
        - "gemini-2.5-flash": Faster
        - "gemini-1.5-pro": Previous generation
    """

    def __init__(self, model: str = "gemini-2.5-pro") -> None:
        """Initialize Gemini CLI client.

        Args:
            model: Model to use (gemini-2.5-pro, gemini-2.5-flash, gemini-1.5-pro)

        Raises:
            RuntimeError: If Gemini CLI not found in PATH
        """
        self.cli_path = shutil.which("gemini")
        if not self.cli_path:
            raise RuntimeError(
                "Gemini CLI not found in PATH. "
                "Install from: https://github.com/google-gemini/gemini-cli"
            )

        self.model = model
        logger.info(f"Gemini CLI initialized: {self.cli_path} (model={model})")

    def is_available(self) -> bool:
        """Check if Gemini CLI is available.

        Returns:
            True if CLI executable found and accessible
        """
        if not self.cli_path:
            return False

        try:
            result = subprocess.run(
                [self.cli_path, "--version"],
                check=False,
                capture_output=True,
                timeout=5,
            )
            # Gemini CLI returns 0 or 1 depending on version
            return result.returncode in [0, 1]
        except Exception as e:
            logger.warning(f"Gemini CLI availability check failed: {e}")
            return False

    def get_model_name(self) -> str:
        """Get model name.

        Returns:
            Model identifier (e.g., "gemini-2.5-pro")
        """
        return self.model

    def authenticate(self) -> bool:
        """Verify Gemini CLI authentication is working.

        The CLI handles authentication via Google OAuth. This method verifies
        that cached credentials are valid by attempting a simple prompt.

        Returns:
            True if authenticated, False otherwise
        """
        if not self.is_available():
            logger.error("Gemini CLI not available")
            return False

        # Test with a simple prompt to verify auth
        try:
            result = subprocess.run(
                [
                    self.cli_path,
                    "--output-format",
                    "json",
                    "-m",
                    self.model,
                ],
                input=b"Say 'auth ok' and nothing else",
                capture_output=True,
                timeout=30,
                check=False,
            )

            if result.returncode != 0:
                stderr = result.stderr.decode() if result.stderr else ""
                logger.error(f"Gemini auth test failed: {stderr}")
                return False

            response_data = json.loads(result.stdout.decode())
            if not response_data.get("response"):
                logger.error("Gemini auth test: no response")
                return False

            logger.info("Gemini authentication verified")
            return True

        except subprocess.TimeoutExpired:
            logger.error("Gemini auth test timed out")
            return False
        except Exception as e:
            logger.error(f"Gemini auth test exception: {e}")
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
        """Generate using Gemini CLI.

        Args:
            prompt: User prompt
            system: System prompt (will be prepended to prompt)
            max_tokens: Maximum tokens (not directly supported by CLI)
            temperature: Sampling temperature (not directly supported by CLI)
            working_dir: Working directory for the CLI (optional)
            **kwargs: Additional options (ignored)

        Returns:
            LLMResponse with Gemini's response

        Raises:
            RuntimeError: If CLI call fails
        """
        if not self.cli_path:
            raise RuntimeError("Gemini CLI not initialized")

        start_time = time.time()

        # Combine system and user prompt (Gemini CLI doesn't have separate system prompt)
        full_prompt = prompt
        if system:
            full_prompt = f"{system}\n\n{prompt}"

        # Build command - Gemini CLI reads prompt from stdin
        cmd = [
            self.cli_path,
            "--output-format",
            "json",
            "-m",
            self.model,
        ]

        logger.debug(
            f"Gemini CLI call: model={self.model}, "
            f"prompt_len={len(full_prompt)}, has_system={system is not None}"
        )

        try:
            # Execute CLI with prompt via stdin
            result = subprocess.run(
                cmd,
                input=full_prompt.encode(),
                capture_output=True,
                timeout=300,  # 5 min
                check=True,
                cwd=working_dir,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Parse JSON response
            response_data = json.loads(result.stdout.decode())

            # Extract response text
            content = str(response_data.get("response", ""))

            # Extract usage stats - aggregate across all models used
            models_stats = response_data.get("stats", {}).get("models", {})
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            cached_tokens = 0

            for model_data in models_stats.values():
                if isinstance(model_data, dict):
                    tokens = model_data.get("tokens", {})
                    prompt_tokens += tokens.get("prompt", 0)
                    completion_tokens += tokens.get("candidates", 0)
                    total_tokens += tokens.get("total", 0)
                    cached_tokens += tokens.get("cached", 0)

            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cached_tokens": cached_tokens,
            }

            logger.info(
                f"Gemini response: {duration_ms}ms, "
                f"{usage['total_tokens']} tokens, {len(content)} chars"
            )

            return LLMResponse(
                content=content,
                provider="gemini",
                model=self.model,
                usage=usage,
                stop_reason="end_turn",
                raw_response=response_data,
            )

        except subprocess.TimeoutExpired:
            logger.error("Gemini CLI timed out after 5 minutes")
            raise RuntimeError("Gemini CLI timed out after 5 minutes")

        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode()[:500] if e.stderr else "none"
            logger.error(f"Gemini CLI failed: exit={e.returncode}, stderr={stderr}")
            raise RuntimeError(f"Gemini CLI failed: {e.stderr}")

        except json.JSONDecodeError as e:
            stdout_preview = (
                result.stdout.decode()[:200] if result.stdout else "(empty)"
            )
            stderr_preview = (
                result.stderr.decode()[:200] if result.stderr else "(empty)"
            )
            logger.error(
                f"Failed to parse Gemini CLI JSON: {e}. "
                f"Stdout: {stdout_preview}, Stderr: {stderr_preview}"
            )
            raise RuntimeError(f"Failed to parse Gemini CLI JSON: {e}")
