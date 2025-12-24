"""Claude client using the official Claude Agent SDK.

Uses the same infrastructure that powers Claude Code.
No API keys needed - uses OAuth via cached credentials.

Supports native SDK tool calling with PreToolUse hooks for permission control.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, ClassVar

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, query
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

# Tool categories for permission handling
READ_TOOLS = {"read_file", "search_code", "list_files", "get_project_structure"}
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "create_directory"}


class ClaudeClient(LLMClient):
    """Claude client using the official Agent SDK.

    Uses ClaudeSDKClient for proper streaming, session management,
    and all Claude Code features. Supports native SDK tool calling
    with PreToolUse hooks for permission control.

    To set up:
    1. Install Claude Code CLI
    2. Run `claude` once to authenticate via browser
    3. Credentials are cached locally (~/.claude/)

    Models (4.5 series - latest):
        - "claude-sonnet-4-5" (default): Claude Sonnet 4.5 - best coding model
        - "claude-opus-4-5": Claude Opus 4.5 - most capable reasoning
        - "claude-haiku-4-5": Claude Haiku 4.5 - fastest, cost-efficient

    Also accepts short names: "sonnet", "opus", "haiku" (mapped to 4.5 series)
    """

    # Map full model IDs to SDK short names
    MODEL_MAP: ClassVar[dict[str, str]] = {
        "claude-opus-4-5": "opus",
        "claude-sonnet-4-5": "sonnet",
        "claude-haiku-4-5": "haiku",
        # Short names pass through
        "opus": "opus",
        "sonnet": "sonnet",
        "haiku": "haiku",
    }

    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        permission_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
        after_tool_callback: Callable[[str, dict[str, Any], str], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize Claude SDK client.

        Args:
            model: Model to use ("claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5")
                   Also accepts short names: "sonnet", "opus", "haiku"
            permission_callback: Async callback for permission prompting.
                Called with (tool_name, tool_args) when write tools need approval.
                Returns True to allow, False to deny.
            after_tool_callback: Async callback after tool execution.
                Called with (tool_name, tool_input, tool_output) for observation capture.
                Non-blocking - errors are logged but don't interrupt execution.
        """
        # Map full model ID to SDK short name
        self.model = self.MODEL_MAP.get(model, model)
        self.model_id = model  # Keep original for display
        self._permission_callback = permission_callback
        self._after_tool_callback = after_tool_callback
        self._cli_path = shutil.which("claude")
        if not self._cli_path:
            raise RuntimeError(
                "Claude CLI not found in PATH. "
                "Install with: npm install -g @anthropic-ai/claude-code"
            )
        logger.info(f"Claude SDK client initialized (model={self.model}, id={model})")

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
        # Run async code synchronously - use asyncio.run() for thread safety
        return asyncio.run(self._generate_async(prompt, system, working_dir))

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

                    elif isinstance(msg, ResultMessage) and hasattr(msg, "total_cost_usd"):
                        # Extract usage from result - estimate tokens from cost
                        pass

            duration_ms = int((time.time() - start_time) * 1000)
            content = "".join(content_parts)

            logger.info(f"Claude SDK response: {duration_ms}ms, {len(content)} chars")

            return LLMResponse(
                content=content,
                provider="claude",
                model=self.model,
                usage=usage,
                stop_reason="end_turn",
            )

        except Exception as e:
            logger.error(f"Claude SDK error: {e}")
            raise RuntimeError(f"Claude SDK error: {e}") from e

    async def generate_with_tools_native(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system: str | None = None,
        write_enabled: bool = False,
        yolo_mode: bool = False,
        working_dir: str | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[tuple[Any, str | None], None]:
        """Generate using SDK's native tool calling with PreToolUse hooks.

        Uses Claude Agent SDK's hook system for permission control instead
        of the custom JSON-based tool protocol.

        Args:
            prompt: User prompt
            tools: Tool definitions in Anthropic API format
            system: System prompt (optional)
            write_enabled: Whether write tools are enabled
            yolo_mode: Auto-approve all write tool requests
            working_dir: Working directory for the agent
            session_id: SDK session ID to resume (optional)

        Yields:
            Tuple of (SDK message object, sdk_session_id).
            sdk_session_id is populated from the init message and included
            with each yield so the caller can capture it.
        """
        # Capture instance variables for closure
        permission_callback = self._permission_callback

        async def permission_hook(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: Any,
        ) -> dict[str, Any]:
            """PreToolUse hook for permission control."""
            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {})
            hook_event_name = input_data.get("hook_event_name", "PreToolUse")

            # Read tools always allowed
            if tool_name in READ_TOOLS:
                logger.debug(f"Auto-allowing read tool: {tool_name}")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "allow",
                    }
                }

            # Write tools need permission
            if tool_name in WRITE_TOOLS:
                if not write_enabled:
                    logger.info(f"Denying write tool (disabled): {tool_name}")
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "Write access not enabled",
                        }
                    }

                if yolo_mode:
                    logger.info(f"Auto-allowing write tool (YOLO mode): {tool_name}")
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": "allow",
                        }
                    }

                # Use permission callback if available
                if permission_callback:
                    try:
                        approved = await permission_callback(tool_name, tool_input)
                        decision = "allow" if approved else "deny"
                        reason = None if approved else "Permission denied by user"
                        logger.info(f"Permission callback for {tool_name}: {decision}")
                        result: dict[str, Any] = {
                            "hookSpecificOutput": {
                                "hookEventName": hook_event_name,
                                "permissionDecision": decision,
                            }
                        }
                        if reason:
                            result["hookSpecificOutput"]["permissionDecisionReason"] = reason
                        return result
                    except Exception as e:
                        logger.error(f"Permission callback error: {e}")
                        return {
                            "hookSpecificOutput": {
                                "hookEventName": hook_event_name,
                                "permissionDecision": "deny",
                                "permissionDecisionReason": f"Permission callback error: {e}",
                            }
                        }

                # No callback configured - deny by default for safety
                logger.warning(f"Denying write tool (no callback): {tool_name}")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "Permission required but no callback configured",
                    }
                }

            # Unknown tools - let them through
            logger.debug(f"Allowing unknown tool: {tool_name}")
            return {}

        # Capture after_tool_callback for closure
        after_tool_callback = self._after_tool_callback

        async def post_tool_hook(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: Any,
        ) -> dict[str, Any]:
            """PostToolUse hook for observation capture."""
            if not after_tool_callback:
                return {}

            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {})
            tool_output = input_data.get("tool_output", "")

            try:
                await after_tool_callback(tool_name, tool_input, tool_output)
            except Exception as e:
                logger.warning(f"After tool callback error: {e}")

            return {}

        # Build hooks dict
        hooks: dict[str, list[HookMatcher]] = {"PreToolUse": [HookMatcher(hooks=[permission_hook])]}
        if after_tool_callback:
            hooks["PostToolUse"] = [HookMatcher(hooks=[post_tool_hook])]

        # Build options with hooks and optional session resume
        options = ClaudeAgentOptions(
            cwd=working_dir or ".",
            cli_path=self._cli_path,
            model=self.model,
            hooks=hooks,
        )

        # Add resume option if session_id provided
        if session_id:
            options.resume = session_id
            logger.info(f"Resuming Claude session: {session_id}")

        # Combine system + prompt if system provided
        full_prompt = prompt
        if system:
            full_prompt = f"{system}\n\n{prompt}"

        # Track the SDK session ID from init message
        sdk_session_id: str | None = None

        try:
            async for message in query(prompt=full_prompt, options=options):
                # Capture session ID from init message
                if (
                    hasattr(message, "subtype")
                    and message.subtype == "init"
                    and hasattr(message, "data")
                ):
                    sdk_session_id = message.data.get("session_id")
                    if sdk_session_id:
                        logger.info(f"Claude SDK session ID: {sdk_session_id}")

                yield (message, sdk_session_id)
        except Exception as e:
            logger.error(f"Claude SDK native tool error: {e}")
            raise RuntimeError(f"Claude SDK native tool error: {e}") from e
