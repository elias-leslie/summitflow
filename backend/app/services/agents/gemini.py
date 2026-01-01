"""Gemini client using the official Google ADK.

Uses google-adk agent framework with native tool support and callbacks.
Authentication via GOOGLE_API_KEY or GEMINI_API_KEY.

Supports native ADK tool calling with before_tool_callback for permission control.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, ClassVar

from ...constants import DEFAULT_GEMINI_MODEL
from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

# Tool categories for permission handling
READ_TOOLS = {"read_file", "search_code", "list_files", "get_project_structure"}
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "create_directory"}


class GeminiClient(LLMClient):
    """Gemini client using the Google Agent Development Kit.

    Uses google-adk agent framework with native tool support, callbacks,
    and streaming. Supports before_tool_callback for permission control.

    To set up:
    1. Set GOOGLE_API_KEY environment variable, OR
    2. Run `gcloud auth application-default login`

    Models:
        - GEMINI_FLASH (default): Gemini 3 Flash - fast and capable
        - GEMINI_PRO: Gemini 3 Pro - most capable reasoning model
    """

    # Class-level session storage for persistence across calls
    _session_service: ClassVar[Any] = None  # InMemorySessionService instance
    _active_sessions: ClassVar[dict[str, str]] = {}  # Maps our session IDs to ADK session IDs

    def __init__(
        self,
        model: str = DEFAULT_GEMINI_MODEL,
        permission_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
        after_tool_callback: Callable[[str, dict[str, Any], str], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize Gemini ADK client.

        Args:
            model: Model to use
            permission_callback: Async callback for permission prompting.
                Called with (tool_name, tool_args) when write tools need approval.
                Returns True to allow, False to deny.
            after_tool_callback: Async callback after tool execution.
                Called with (tool_name, tool_input, tool_output) for observation capture.
                Non-blocking - errors are logged but don't interrupt execution.
        """
        self.model = model
        self._permission_callback = permission_callback
        self._after_tool_callback = after_tool_callback
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

            google.auth.default()  # type: ignore[no-untyped-call]
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
            raise RuntimeError(f"Gemini error: {e}") from e

    def _create_before_tool_callback(
        self,
        write_enabled: bool,
        yolo_mode: bool,
    ) -> Callable[..., Any]:
        """Create permission-aware before_tool_callback for ADK agent.

        The callback runs before each tool execution and can:
        - Return None to allow the tool to execute
        - Return a dict to skip the tool and use that as the result

        Args:
            write_enabled: Whether write tools are enabled
            yolo_mode: Auto-approve all write tool requests

        Returns:
            Callback function for LlmAgent.before_tool_callback
        """
        permission_callback = self._permission_callback

        async def before_tool_callback(
            tool: Any,  # BaseTool
            args: dict[str, Any],
            context: Any,  # ToolContext
        ) -> dict[str, Any] | None:
            """Permission-aware tool callback."""
            # Get tool name from the tool object
            tool_name = getattr(tool, "name", str(tool))

            # Read tools always allowed
            if tool_name in READ_TOOLS:
                logger.debug(f"Auto-allowing read tool: {tool_name}")
                return None  # Allow execution

            # Write tools need permission
            if tool_name in WRITE_TOOLS:
                if not write_enabled:
                    logger.info(f"Blocking write tool (disabled): {tool_name}")
                    return {"error": "Write access not enabled"}

                if yolo_mode:
                    logger.info(f"Auto-allowing write tool (YOLO mode): {tool_name}")
                    return None  # Allow execution

                # Use permission callback if available
                if permission_callback:
                    try:
                        approved = await permission_callback(tool_name, args)
                        if approved:
                            logger.info(f"Permission granted for {tool_name}")
                            return None  # Allow execution
                        else:
                            logger.info(f"Permission denied for {tool_name}")
                            return {"error": "Permission denied by user"}
                    except Exception as e:
                        logger.error(f"Permission callback error: {e}")
                        return {"error": f"Permission callback error: {e}"}

                # No callback configured - block for safety
                logger.warning(f"Blocking write tool (no callback): {tool_name}")
                return {"error": "Permission required but no callback configured"}

            # Unknown tools - let them through
            logger.debug(f"Allowing unknown tool: {tool_name}")
            return None

        return before_tool_callback

    def _create_after_tool_callback(self) -> Callable[..., Any] | None:
        """Create after_tool_callback for observation capture.

        The callback runs after each tool execution for fire-and-forget capture.

        Returns:
            Callback function for LlmAgent.after_tool_callback, or None if no callback.
        """
        after_tool_callback = self._after_tool_callback
        if not after_tool_callback:
            return None

        async def after_tool_cb(
            tool: Any,  # BaseTool
            args: dict[str, Any],
            context: Any,  # ToolContext
            result: dict[str, Any],
        ) -> dict[str, Any] | None:
            """After tool callback for observation capture."""
            tool_name = getattr(tool, "name", str(tool))
            # Convert result to string for observation
            tool_output = str(result.get("output", result.get("error", str(result))))

            try:
                await after_tool_callback(tool_name, args, tool_output)
            except Exception as e:
                logger.warning(f"After tool callback error: {e}")

            return None  # Don't modify result

        return after_tool_cb

    async def generate_with_tools_native(
        self,
        prompt: str,
        tools: list[Callable[..., Any]],
        system: str | None = None,
        write_enabled: bool = False,
        yolo_mode: bool = False,
        working_dir: str | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[tuple[Any, str], None]:
        """Generate using ADK's native agent framework with tool callbacks.

        Uses google-adk's LlmAgent with before_tool_callback for permission
        control instead of the custom JSON-based tool protocol.

        Args:
            prompt: User prompt
            tools: List of callable tool functions (with proper __name__ and __doc__)
            system: System prompt / instruction
            write_enabled: Whether write tools are enabled
            yolo_mode: Auto-approve all write tool requests
            working_dir: Working directory (not used directly by ADK)
            session_id: Gemini session ID to resume (optional)

        Yields:
            Tuple of (ADK event object, gemini_session_id).
            gemini_session_id is the same for all yields in a session.
        """
        from google.adk.agents import LlmAgent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        # Create agent with tools and callbacks
        after_tool_cb = self._create_after_tool_callback()
        agent = LlmAgent(
            name="gemini_roundtable",
            model=self.model,
            instruction=system or "You are a helpful assistant.",
            tools=tools,  # type: ignore[arg-type]
            before_tool_callback=self._create_before_tool_callback(write_enabled, yolo_mode),
            after_tool_callback=after_tool_cb,
        )

        # Initialize class-level session service if needed
        if GeminiClient._session_service is None:
            GeminiClient._session_service = InMemorySessionService()  # type: ignore[no-untyped-call]

        # Use the shared session service for persistence
        runner = Runner(
            agent=agent,
            app_name="roundtable",
            session_service=GeminiClient._session_service,
        )

        # Reuse existing session ID or generate new one
        if session_id and session_id in GeminiClient._active_sessions:
            gemini_session_id = session_id
            logger.info(f"Resuming Gemini session: {gemini_session_id}")
        else:
            gemini_session_id = f"gemini-{uuid.uuid4().hex[:12]}"
            GeminiClient._active_sessions[gemini_session_id] = gemini_session_id
            logger.info(f"Created new Gemini session: {gemini_session_id}")

        # Use a consistent user ID for the session
        user_id = f"user-{gemini_session_id[:8]}"

        # Create the message content
        message_content = types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        )

        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=gemini_session_id,
                new_message=message_content,
            ):
                yield (event, gemini_session_id)
        except Exception as e:
            logger.error(f"Gemini ADK native tool error: {e}")
            raise RuntimeError(f"Gemini ADK native tool error: {e}") from e
