"""Roundtable service for multi-agent collaboration.

Routes messages between user and multiple AI agents (Claude, Gemini).
Supports targeting specific agents or broadcasting to both.
Agents have read-only access to the codebase via tools.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Literal

from ...constants import DEFAULT_CLAUDE_MODEL, DEFAULT_GEMINI_MODEL
from ...utils.async_helpers import run_async_in_sync_context
from ..agent_hub_client import AgentHubLLMClient, AgentType, get_agent
from ..agents import LLMResponse

# MIGRATION NOTE: Native SDK clients removed. Using Agent Hub client.
# Streaming tool execution (generate_with_tools_native) not yet supported.
# See: task-37346c12 for streaming tool support.
from .extraction import (
    accept_spec,
    extract_spec_from_conversation,
    get_effective_prompt,
)

# NOTE: to_adk_function_tools and to_claude_sdk_tools removed - not needed
# until streaming tool support is added to Agent Hub
from .permissions import permission_manager
from .prompts import build_prompt_with_context, build_system_prompt
from .session import RoundtableMessage, RoundtableSession

logger = logging.getLogger(__name__)

# Type alias for permission callback
PermissionCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]

# Context variable for current session ID (used by permission callback)
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_session_id", default=None
)


async def default_permission_callback(tool_name: str, tool_args: dict[str, Any]) -> bool:
    """Default permission callback that uses the PermissionManager.

    Uses the session_id from the current context to register the permission
    request and waits for user approval via the API.

    Args:
        tool_name: Name of the tool requesting permission
        tool_args: Arguments passed to the tool

    Returns:
        True if approved, False if denied or timed out
    """
    session_id = current_session_id.get()
    if session_id is None:
        logger.warning("Permission callback called without session_id context, denying")
        return False

    return await permission_manager.request_permission(
        session_id=session_id,
        tool_name=tool_name,
        tool_args=tool_args,
    )


TargetAgent = Literal["claude", "gemini", "both"]


class RoundtableService:
    """Service for multi-agent roundtable conversations.

    Supports:
    - Routing messages to specific agents
    - Broadcasting to both agents
    - Maintaining conversation context
    - Turn-taking between agents
    """

    def __init__(
        self,
        claude_model: str = DEFAULT_CLAUDE_MODEL,
        gemini_model: str = DEFAULT_GEMINI_MODEL,
        permission_callback: PermissionCallback | None = None,
    ) -> None:
        """Initialize roundtable service with model configurations.

        Args:
            claude_model: Model for Claude agent
            gemini_model: Model for Gemini agent
            permission_callback: Async callback for write tool permission prompts.
                Called with (tool_name, tool_args) when write tools need approval.
                Returns True to allow, False to deny.
        """
        self.claude_model = claude_model
        self.gemini_model = gemini_model
        self._permission_callback = permission_callback
        self._sessions: dict[str, RoundtableSession] = {}

        # Create Agent Hub clients
        # NOTE: Permission callbacks not supported via Agent Hub yet
        # TODO: Add permission hook support to Agent Hub API
        self._claude_client = AgentHubLLMClient(model=claude_model, provider="claude")
        self._gemini_client = AgentHubLLMClient(model=gemini_model, provider="gemini")

    def get_session(self, session_id: str) -> RoundtableSession | None:
        """Get an existing session by ID."""
        return self._sessions.get(session_id)

    def _add_user_message(self, session: RoundtableSession, message: str) -> None:
        """Add a user message to the session."""
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

    def _persist_sdk_session_id(
        self, agent_type: AgentType, new_id: str | None, session: RoundtableSession
    ) -> None:
        """Persist SDK session ID if it changed."""
        if not new_id:
            return

        current_id = (
            session.claude_sdk_session_id
            if agent_type == "claude"
            else session.gemini_sdk_session_id
        )
        if new_id == current_id:
            return

        # Import here to avoid circular imports
        from app.storage import roundtable as roundtable_storage

        if agent_type == "claude":
            session.claude_sdk_session_id = new_id
            roundtable_storage.update_sdk_session_ids(
                session_id=session.id, claude_sdk_session_id=new_id
            )
        else:
            session.gemini_sdk_session_id = new_id
            roundtable_storage.update_sdk_session_ids(
                session_id=session.id, gemini_sdk_session_id=new_id
            )
        logger.info(f"Persisted {agent_type} SDK session ID: {new_id}")

    def create_session(
        self,
        project_id: str,
        mode: Literal["spec_driven", "quick"] = "quick",
        tools_enabled: bool = True,
    ) -> RoundtableSession:
        """Create a new roundtable session."""
        session = RoundtableSession.create(project_id, mode, tools_enabled)
        self._sessions[session.id] = session
        return session

    def _create_response_message(
        self,
        agent_type: AgentType,
        response: LLMResponse,
        session: RoundtableSession,
    ) -> RoundtableMessage:
        """Create and store a response message from an agent.

        Args:
            agent_type: The type of agent ("claude" or "gemini")
            response: The LLM response object
            session: The session to add the message to

        Returns:
            The created RoundtableMessage
        """
        msg = RoundtableMessage.create(
            agent_type,
            response.content,
            tokens_used=response.usage.get("total_tokens", 0),
            model=response.model,
        )
        session.add_message(msg)
        return msg

    def _create_error_message(
        self,
        agent_type: AgentType,
        error: Exception,
        session: RoundtableSession,
    ) -> RoundtableMessage:
        """Create and store an error message for an agent.

        Args:
            agent_type: The type of agent ("claude" or "gemini")
            error: The exception that occurred
            session: The session to add the message to

        Returns:
            The created error RoundtableMessage
        """
        logger.error(f"{agent_type.capitalize()} error: {error}")
        error_msg = RoundtableMessage.create(agent_type, f"[Error: {error!s}]")
        session.add_message(error_msg)
        return error_msg

    async def route_message_async(
        self,
        session: RoundtableSession,
        message: str,
        target: TargetAgent = "both",
    ) -> AsyncGenerator[RoundtableMessage, None]:
        """Route a message asynchronously, yielding responses as they arrive.

        Args:
            session: The roundtable session
            message: User's message
            target: Target agent ("claude", "gemini", or "both")

        Yields:
            Response messages from agent(s) as they complete
        """
        self._add_user_message(session, message)

        # Build context from conversation history
        context = session.get_context()

        if target in ("claude", "both"):
            try:
                # Run in thread pool to avoid blocking
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._send_to_agent,
                    "claude",
                    message,
                    context,
                )
                yield self._create_response_message("claude", response, session)

                # Update context with Claude's response for Gemini
                context = session.get_context()
            except Exception as e:
                yield self._create_error_message("claude", e, session)

        if target in ("gemini", "both"):
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._send_to_agent,
                    "gemini",
                    message,
                    context,
                )
                yield self._create_response_message("gemini", response, session)
            except Exception as e:
                yield self._create_error_message("gemini", e, session)

    def _send_to_agent(
        self,
        agent_type: AgentType,
        message: str,
        context: str,
        session: RoundtableSession | None = None,
    ) -> LLMResponse:
        """Send message to a specific agent with context.

        Note: Tool access has been migrated to the async route_message_with_native_tools()
        path which uses SDK-native tool calling. This method provides non-tool generation
        for backward compatibility. New code should use route_message_with_native_tools().
        """
        model = self.claude_model if agent_type == "claude" else self.gemini_model
        agent = get_agent(agent_type, model=model)

        # Build prompts using shared utilities
        # Note: tools_enabled flag is ignored in this path (deprecated)
        system_prompt = build_system_prompt(agent_type, False)
        prompt = build_prompt_with_context(message, context, agent_type)

        # Simple generation without tools
        return agent.generate(
            prompt=prompt,
            system=system_prompt,
            max_tokens=4096,
            temperature=0.7,
        )

    async def _send_with_tools_native(
        self,
        agent_type: AgentType,
        prompt: str,
        system: str,
        session: RoundtableSession,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Send message with native SDK tool calling.

        Uses Claude SDK hooks or Google ADK callbacks for tool permission
        control instead of custom JSON protocol.

        Args:
            agent_type: Which agent to use ("claude" or "gemini")
            prompt: User prompt
            system: System prompt
            session: Session with tool executor

        Yields:
            Event dicts with message content, tool calls, and captured SDK session IDs
        """
        # TODO(task-37346c12): Add streaming tool support to Agent Hub API
        # Native SDK tool calling (generate_with_tools_native) has been removed.
        # Agent Hub client supports basic tool calling via complete() with tools param,
        # but NOT streaming tool execution with permission callbacks.
        raise NotImplementedError(
            f"Streaming tool execution for {agent_type} not yet supported via Agent Hub. "
            "Use simple completions with tools parameter, or create task for streaming support."
        )
        # Make this an async generator to match the function signature
        yield {}  # Unreachable but needed for type checking

    async def route_message_with_native_tools(
        self,
        session: RoundtableSession,
        message: str,
        target: TargetAgent = "both",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Route message using native SDK tool calling with permission callbacks.

        This is the new SDK-native method that replaces the custom JSON protocol.
        Uses Claude SDK hooks and Google ADK callbacks for tool permissions.

        Args:
            session: The roundtable session
            message: User's message
            target: Target agent ("claude", "gemini", or "both")

        Yields:
            Event dicts containing agent responses and tool calls
        """
        self._add_user_message(session, message)

        # Build context and prompts
        context = session.get_context()
        prompt = build_prompt_with_context(message, context)

        if target in ("claude", "both"):
            system = build_system_prompt("claude", session.tools_enabled)
            async for event in self._send_with_tools_native("claude", prompt, system, session):
                yield event

        if target in ("gemini", "both"):
            # Update context if Claude already responded
            if target == "both":
                context_updated = session.get_context()
                prompt = build_prompt_with_context(message, context_updated)

            system = build_system_prompt("gemini", session.tools_enabled)
            async for event in self._send_with_tools_native("gemini", prompt, system, session):
                yield event

    # =========================================================================
    # Observation Capture
    # =========================================================================

    def _capture_observation(
        self,
        project_id: str,
        session_id: str,
        agent_type: str,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: str,
    ) -> None:
        """Fire-and-forget observation capture for tool executions.

        Enqueues tool execution for async observation extraction.
        Does not block on failure - logs errors but continues.
        """
        try:
            from ..memory import ObservationQueue

            queue = ObservationQueue()

            # Run async enqueue in sync context
            run_async_in_sync_context(
                queue.enqueue(
                    project_id=project_id,
                    session_id=session_id,
                    agent_type=agent_type,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=tool_output,
                )
            )
        except Exception as e:
            # Don't break roundtable for observation capture failures
            logger.warning(f"Failed to capture observation: {e}")

    # =========================================================================
    # Prompt Configuration
    # =========================================================================

    def get_effective_prompt(self, project_id: str, prompt_type: str) -> dict[str, Any]:
        """Get the effective prompt for a project (custom or default).

        Args:
            project_id: Project ID
            prompt_type: Type of prompt (feature_extraction, vision_extraction, goals_extraction)

        Returns:
            Prompt configuration dict with prompt_text, primary_agent, primary_model, etc.
        """
        return get_effective_prompt(project_id, prompt_type)

    # =========================================================================
    # TDD Spec Extraction - Components, Capabilities, Tests
    # =========================================================================

    def extract_spec_from_conversation(
        self,
        session: RoundtableSession,
        agent_type: AgentType = "gemini",
    ) -> dict[str, Any]:
        """Extract TDD spec (components, capabilities, tests) from a Roundtable conversation.

        Args:
            session: The roundtable session to analyze
            agent_type: Which agent to use for extraction

        Returns:
            Dict with 'components' key containing the spec structure
        """
        return extract_spec_from_conversation(
            session=session,
            agent_type=agent_type,
            claude_model=self.claude_model,
            gemini_model=self.gemini_model,
        )

    def accept_spec(
        self,
        project_id: str,
        session_id: str,
        accepted_by: str = "user",
    ) -> dict[str, Any]:
        """Accept the generated spec and create permanent entities.

        This converts the ephemeral generated_spec into permanent:
        - accepted_specs record (permanent spec record)
        - tdd_components
        - tdd_capabilities
        - tdd_tests (with test_capability_links)

        Args:
            project_id: Project ID
            session_id: Roundtable session ID containing the spec
            accepted_by: Who accepted (user or agent name)

        Returns:
            Dict with spec_id and creation counts
        """
        return accept_spec(project_id, session_id, accepted_by)

    # =========================================================================
    # Session Lifecycle
    # =========================================================================

    def end_session(
        self,
        session: RoundtableSession,
        summary: str | None = None,
        completed_steps: list[str] | None = None,
        remaining_steps: list[str] | None = None,
        create_checkpoint: bool = True,
    ) -> dict[str, Any] | None:
        """End a session and optionally create a checkpoint.

        Args:
            session: The session to end
            summary: Summary of what was accomplished
            completed_steps: Steps that were completed
            remaining_steps: Steps still remaining
            create_checkpoint: Whether to create a checkpoint (default True)

        Returns:
            Created checkpoint if create_checkpoint=True, else None
        """
        from ..memory import CheckpointService

        checkpoint = None

        if create_checkpoint:
            # Calculate tokens used from messages
            total_tokens = sum(msg.tokens_used for msg in session.messages)

            # Extract files modified from conversation (if any)
            files_modified = self._extract_files_from_session(session)

            # Build conversation summary if not provided
            if not summary and session.messages:
                summary = self._build_session_summary(session)

            # Create checkpoint
            checkpoint_service = CheckpointService(session.project_id)
            checkpoint = checkpoint_service.create_from_session_end(
                session_id=session.id,
                agent_type=session.get_effective_agent(),
                summary=summary or "Session ended",
                completed=completed_steps,
                remaining=remaining_steps,
                files=files_modified,
                tokens=total_tokens,
            )

            logger.info(f"Session {session.id} ended with checkpoint {checkpoint['id']}")

        # Create diary entry for the session
        self._create_diary_entry(session, summary, completed_steps)

        # Remove from active sessions
        if session.id in self._sessions:
            del self._sessions[session.id]

        return checkpoint

    def _create_diary_entry(
        self,
        session: RoundtableSession,
        summary: str | None = None,
        completed_steps: list[str] | None = None,
    ) -> None:
        """Create a diary entry for the session and check reflection trigger.

        Args:
            session: The session that ended
            summary: Session summary
            completed_steps: Steps that were completed
        """
        from ..memory import DiaryService

        try:
            # Calculate tokens and duration
            total_tokens = sum(msg.tokens_used for msg in session.messages)
            duration = None
            if session.messages:
                first_msg = session.messages[0].timestamp
                last_msg = session.messages[-1].timestamp
                duration = int((last_msg - first_msg).total_seconds())

            # Determine outcome based on completed steps
            outcome = "neutral"
            if completed_steps:
                outcome = "success"

            # Create diary entry
            diary_service = DiaryService(session.project_id)
            entry = diary_service.create_from_session_end(
                session_id=session.id,
                agent_type=session.get_effective_agent(),
                outcome=outcome,
                tokens=total_tokens,
                duration=duration,
            )

            logger.info(f"Diary entry created: {entry['id']} for session {session.id}")

            # Check if reflection should be triggered
            self._check_reflection_trigger(session.project_id)

        except Exception as e:
            # Don't fail session end if diary creation fails
            logger.warning(f"Failed to create diary entry: {e}")

    def _check_reflection_trigger(self, project_id: str) -> None:
        """Check if reflection should be triggered and schedule if needed."""
        try:
            from ...tasks.reflection_processor import check_reflection_trigger

            # Fire and forget - don't wait for result
            check_reflection_trigger.delay(project_id=project_id)
            logger.debug(f"Reflection trigger check scheduled for {project_id}")
        except Exception as e:
            logger.warning(f"Failed to schedule reflection check: {e}")

    def _extract_files_from_session(self, session: RoundtableSession) -> list[str]:
        """Extract file paths mentioned in session messages.

        Simple extraction of file paths from conversation.
        """
        import re

        files = set()
        for msg in session.messages:
            # Match common file path patterns
            # e.g., /path/to/file.py, ./relative/path.ts
            matches = re.findall(
                r'(?:^|[\s"`\'(])([./][\w./\-]+\.\w{1,10})(?:[\s"`\'):]|$)', msg.content
            )
            files.update(matches)
        return list(files)[:20]  # Limit to 20 files

    def _build_session_summary(self, session: RoundtableSession, max_messages: int = 10) -> str:
        """Build a brief summary of the session from recent messages."""
        recent = session.messages[-max_messages:]
        parts = []
        for msg in recent:
            speaker = msg.agent.upper() if msg.agent != "user" else "USER"
            # Truncate long messages
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            parts.append(f"[{speaker}]: {content}")
        return "\n".join(parts)


# Module-level singleton for convenience
_roundtable_service: RoundtableService | None = None


def get_roundtable_service() -> RoundtableService:
    """Get or create the roundtable service singleton.

    The singleton is created with the default permission callback that
    uses the PermissionManager for user approval prompts.
    """
    global _roundtable_service
    if _roundtable_service is None:
        _roundtable_service = RoundtableService(
            permission_callback=default_permission_callback,
        )
    return _roundtable_service
