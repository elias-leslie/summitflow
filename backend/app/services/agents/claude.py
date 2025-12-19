"""Claude CLI client for SummitFlow.

Uses the Claude Code CLI with OAuth authentication (no API key needed).
Included with Claude subscription ($20/month).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from typing import Any

from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class ClaudeClient(LLMClient):
    """Claude Code CLI client.

    Uses local Claude CLI with OAuth authentication (no API keys).
    Authentication is handled automatically by the CLI via cached credentials.

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
        """Initialize Claude CLI client.

        Args:
            model: Model to use ("sonnet", "opus", "haiku", or full model name)

        Raises:
            RuntimeError: If Claude CLI not found in PATH
        """
        self.cli_path = shutil.which("claude")
        if not self.cli_path:
            raise RuntimeError(
                "Claude CLI not found in PATH. "
                "Install with: npm install -g @anthropic-ai/claude-code"
            )

        self.model = model
        logger.info(f"Claude CLI initialized: {self.cli_path} (model={model})")

    def is_available(self) -> bool:
        """Check if Claude CLI is available and authenticated.

        Returns:
            True if CLI executable found and version command works
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
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"Claude CLI availability check failed: {e}")
            return False

    def get_model_name(self) -> str:
        """Get model name.

        Returns:
            Model identifier (e.g., "claude-sonnet")
        """
        return f"claude-{self.model}"

    def authenticate(self) -> bool:
        """Verify Claude CLI authentication is working.

        The CLI handles authentication via OAuth. This method verifies
        that cached credentials are valid by attempting a version check.

        Returns:
            True if authenticated, False otherwise
        """
        if not self.is_available():
            logger.error("Claude CLI not available")
            return False

        # Test with a simple prompt to verify auth
        try:
            result = subprocess.run(
                [
                    self.cli_path,
                    "-p",
                    "Say 'auth ok' and nothing else",
                    "--output-format",
                    "json",
                    "--model",
                    self.model,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env={**os.environ, "ANTHROPIC_API_KEY": ""},  # Force OAuth
            )

            if result.returncode != 0:
                logger.error(f"Claude auth test failed: {result.stderr}")
                return False

            response_data = json.loads(result.stdout)
            if response_data.get("is_error"):
                logger.error(f"Claude auth error: {response_data.get('result')}")
                return False

            logger.info("Claude authentication verified")
            return True

        except subprocess.TimeoutExpired:
            logger.error("Claude auth test timed out")
            return False
        except Exception as e:
            logger.error(f"Claude auth test exception: {e}")
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
        """Generate using Claude CLI.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            max_tokens: Maximum tokens (not directly supported by CLI)
            temperature: Sampling temperature (not directly supported by CLI)
            working_dir: Working directory for the CLI (optional)
            **kwargs: Additional options (ignored)

        Returns:
            LLMResponse with Claude's response

        Raises:
            RuntimeError: If CLI call fails
        """
        if not self.cli_path:
            raise RuntimeError("Claude CLI not initialized")

        start_time = time.time()

        # Build command
        cmd = [
            self.cli_path,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            self.model,
            "--permission-mode",
            "bypassPermissions",
        ]

        # Add system prompt if provided
        if system:
            cmd.extend(["--system-prompt", system])

        logger.debug(
            f"Claude CLI call: model={self.model}, "
            f"prompt_len={len(prompt)}, has_system={system is not None}"
        )

        try:
            # Execute CLI with cleared API key (forces OAuth)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 min
                check=True,
                cwd=working_dir,
                env={**os.environ, "ANTHROPIC_API_KEY": ""},
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Parse JSON response
            response_data = json.loads(result.stdout)

            # Check for errors
            if response_data.get("is_error"):
                error_msg = str(response_data.get("result", "Unknown error"))
                logger.error(f"Claude CLI error: {error_msg}")
                raise RuntimeError(f"Claude CLI returned error: {error_msg}")

            # Extract response text
            content = str(response_data.get("result", ""))

            # Extract usage stats
            usage_data = response_data.get("usage", {})
            usage = {
                "prompt_tokens": usage_data.get("input_tokens", 0),
                "completion_tokens": usage_data.get("output_tokens", 0),
                "total_tokens": (
                    usage_data.get("input_tokens", 0)
                    + usage_data.get("output_tokens", 0)
                ),
                "cache_creation_tokens": usage_data.get(
                    "cache_creation_input_tokens", 0
                ),
                "cache_read_tokens": usage_data.get("cache_read_input_tokens", 0),
            }

            logger.info(
                f"Claude response: {duration_ms}ms, "
                f"{usage['total_tokens']} tokens, {len(content)} chars"
            )

            return LLMResponse(
                content=content,
                provider="claude",
                model=self.model,
                usage=usage,
                stop_reason="end_turn",
                raw_response=response_data,
            )

        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out after 5 minutes")
            raise RuntimeError("Claude CLI timed out after 5 minutes")

        except subprocess.CalledProcessError as e:
            logger.error(
                f"Claude CLI failed: exit={e.returncode}, "
                f"stderr={e.stderr[:500] if e.stderr else 'none'}"
            )
            raise RuntimeError(f"Claude CLI failed: {e.stderr}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude CLI JSON: {e}")
            raise RuntimeError(f"Failed to parse Claude CLI JSON: {e}")
