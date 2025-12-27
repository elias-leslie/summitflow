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

from ..agents import AgentType, LLMResponse, get_agent
from ..agents.claude import ClaudeClient
from ..agents.gemini import GeminiClient
from .executor import (
    WRITE_TOOL_NAMES,
    ToolResult,
    format_tool_results_for_prompt,
    to_adk_function_tools,
    to_claude_sdk_tools,
)
from .extraction import (
    SPEC_EXTRACTION_PROMPT,
    accept_spec,
    extract_spec_from_conversation,
    get_effective_prompt,
)
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

    # Re-export extraction functions as methods for backward compatibility
    SPEC_EXTRACTION_PROMPT = SPEC_EXTRACTION_PROMPT

    def __init__(
        self,
        claude_model: str = "claude-sonnet-4-5",
        gemini_model: str = "gemini-3-flash-preview",
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

        # Create agent clients with permission callback
        self._claude_client = ClaudeClient(
            model=claude_model,
            permission_callback=permission_callback,
        )
        self._gemini_client = GeminiClient(
            model=gemini_model,
            permission_callback=permission_callback,
        )

    def get_session(self, session_id: str) -> RoundtableSession | None:
        """Get an existing session by ID."""
        return self._sessions.get(session_id)

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

    def route_message(
        self,
        session: RoundtableSession,
        message: str,
        target: TargetAgent = "both",
    ) -> list[RoundtableMessage]:
        """Route a message to target agent(s) and get responses.

        Args:
            session: The roundtable session
            message: User's message
            target: Target agent ("claude", "gemini", or "both")

        Returns:
            List of response messages from agent(s)
        """
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

        responses: list[RoundtableMessage] = []

        # Build context from conversation history
        context = session.get_context()

        if target in ("claude", "both"):
            try:
                response = self._send_to_agent("claude", message, context)
                responses.append(self._create_response_message("claude", response, session))
            except Exception as e:
                responses.append(self._create_error_message("claude", e, session))

        if target in ("gemini", "both"):
            # If both agents, update context with Claude's response
            if target == "both" and responses:
                context = session.get_context()

            try:
                response = self._send_to_agent("gemini", message, context)
                responses.append(self._create_response_message("gemini", response, session))
            except Exception as e:
                responses.append(self._create_error_message("gemini", e, session))

        return responses

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
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

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
        """Send message to a specific agent with context and optional tool access.

        If session has tools_enabled=True, agents can use read-only codebase tools.
        The agent may call tools multiple times before providing a final response.
        """
        model = self.claude_model if agent_type == "claude" else self.gemini_model
        agent = get_agent(agent_type, model=model)

        # Build prompts using shared utilities
        tools_enabled = session.tools_enabled if session else False
        system_prompt = build_system_prompt(agent_type, tools_enabled)
        prompt = build_prompt_with_context(message, context, agent_type)

        # Check if tools are enabled
        if session and session.tools_enabled:
            return self._send_with_tools(
                agent=agent,
                prompt=prompt,
                system=system_prompt,
                session=session,
                session_id=session.id,
            )

        # No tools - simple generation
        return agent.generate(
            prompt=prompt,
            system=system_prompt,
            max_tokens=4096,
            temperature=0.7,
        )

    def _send_with_tools(
        self,
        agent: Any,
        prompt: str,
        system: str,
        session: RoundtableSession,
        max_iterations: int = 30,
        max_tool_calls: int = 100,
        detect_duplicates: bool = True,
        session_id: str | None = None,
    ) -> LLMResponse:
        """Send message with tool access, handling tool calls in a loop.

        .. deprecated::
            This method uses the legacy JSON-based tool protocol. For new code,
            use `_send_with_tools_native()` which uses Claude SDK hooks and
            Google ADK callbacks for native tool support and better session
            management.

        Uses multiple safeguards to prevent runaway agents:
        - max_iterations: Maximum rounds of tool calls (safety net)
        - max_tool_calls: Total tool calls allowed across all iterations
        - detect_duplicates: Stop if agent calls same tool with same params

        Args:
            agent: LLM client to use
            prompt: User prompt
            system: System prompt
            session: Session with tool executor
            max_iterations: Maximum tool call rounds (default 30)
            max_tool_calls: Maximum total tool calls (default 100)
            detect_duplicates: Stop on repeated identical calls (default True)
            session_id: Session ID for permission callbacks (optional)

        Returns:
            Final LLMResponse after all tool calls are complete
        """
        import json as json_module
        import warnings

        warnings.warn(
            "_send_with_tools() uses the legacy JSON protocol. "
            "Use _send_with_tools_native() for SDK-native tool support.",
            DeprecationWarning,
            stacklevel=2,
        )

        tools = session.tool_executor.get_available_tools()
        current_prompt = prompt
        conversation_history: list[dict[str, Any]] = []

        # Track tool usage for limits
        total_tool_calls = 0
        seen_calls: set[str] = set()
        response = None

        for iteration in range(max_iterations):
            # Generate with tools
            response = agent.generate_with_tools(
                prompt=current_prompt,
                tools=tools,
                system=system,
                conversation_history=conversation_history,
                max_tokens=4096,
                temperature=0.7,
            )

            # If no tool calls, we're done
            if response.stop_reason != "tool_use" or not response.tool_calls:
                logger.info(
                    f"Agent completed after {iteration} iterations, "
                    f"{total_tool_calls} total tool calls"
                )
                return response

            # Execute tool calls with safety checks
            tool_results = []
            should_stop = False

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                parameters = tool_call.get("parameters", {})

                # Check for duplicate calls (agent confusion)
                if detect_duplicates:
                    call_key = f"{tool_name}:{json_module.dumps(parameters, sort_keys=True)}"
                    if call_key in seen_calls:
                        logger.warning(f"Duplicate tool call detected: {tool_name}, stopping")
                        should_stop = True
                        break
                    seen_calls.add(call_key)

                # Check tool call budget
                total_tool_calls += 1
                if total_tool_calls > max_tool_calls:
                    logger.warning(f"Tool call budget exhausted ({max_tool_calls} calls)")
                    should_stop = True
                    break

                logger.info(f"Executing tool [{total_tool_calls}/{max_tool_calls}]: {tool_name}")

                # Check if this is a write tool that needs permission
                if tool_name in WRITE_TOOL_NAMES:
                    if not session.tool_executor.has_write_access():
                        # Write access not enabled - block
                        result = ToolResult(
                            success=False,
                            output="",
                            error=f"Write access not enabled for {tool_name}",
                        )
                        tool_results.append((tool_name, result))
                        continue

                    if not session.tool_executor.yolo_mode:
                        # Need to request permission
                        effective_session_id = session_id or current_session_id.get()
                        if effective_session_id and self._permission_callback:
                            # Set the context for the permission callback
                            current_session_id.set(effective_session_id)
                            # Use asyncio to run the async permission callback
                            try:
                                loop = asyncio.new_event_loop()
                                approved = loop.run_until_complete(
                                    self._permission_callback(tool_name, parameters)
                                )
                                loop.close()

                                if not approved:
                                    result = ToolResult(
                                        success=False,
                                        output="",
                                        error=f"Permission denied for {tool_name}",
                                    )
                                    tool_results.append((tool_name, result))
                                    logger.info(f"Permission denied for {tool_name}")
                                    continue

                                logger.info(f"Permission granted for {tool_name}")
                            except Exception as e:
                                logger.error(f"Permission callback error: {e}")
                                result = ToolResult(
                                    success=False,
                                    output="",
                                    error=f"Permission check failed: {e}",
                                )
                                tool_results.append((tool_name, result))
                                continue
                        else:
                            # No session context or callback - deny for safety
                            logger.warning(f"No permission callback for {tool_name}, denying")
                            result = ToolResult(
                                success=False,
                                output="",
                                error="Permission required but no callback configured",
                            )
                            tool_results.append((tool_name, result))
                            continue

                result = session.tool_executor.execute(tool_name, parameters)
                tool_results.append((tool_name, result))

                logger.info(
                    f"Tool {tool_name} result: success={result.success}, "
                    f"output_len={len(result.output)}"
                )

                # Capture observation (fire-and-forget)
                if result.success:
                    self._capture_observation(
                        project_id=session.project_id,
                        session_id=session.id,
                        agent_type=session.agent_override or "unknown",
                        tool_name=tool_name,
                        tool_input=parameters,
                        tool_output=result.output,
                    )

            # If we hit a limit, return current response
            if should_stop:
                return response

            # Add to conversation history
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": response.content,
                }
            )

            # Format tool results for next prompt
            results_text = format_tool_results_for_prompt(tool_results)
            conversation_history.append(
                {
                    "role": "user",
                    "content": f"Tool results:\n\n{results_text}\n\nContinue with your analysis.",
                }
            )

            # Update prompt for next iteration
            current_prompt = (
                f"You called the following tools. Here are the results:\n\n"
                f"{results_text}\n\n"
                f"Based on these results, continue your analysis. "
                f"If you need more information, call additional tools. "
                f"When you have enough information, provide your final response as plain text."
            )

        # Max iterations reached
        logger.warning(
            f"Agent reached max iterations ({max_iterations}), {total_tool_calls} tool calls made"
        )
        if response is None:
            # Fallback in case max_iterations was 0
            from ..agents.base import LLMResponse

            response = LLMResponse(
                content="No iterations were executed (max_iterations=0)",
                provider="unknown",
                model="unknown",
                stop_reason="max_iterations_zero",
            )
        return response

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
        from app.storage import roundtable as roundtable_storage

        tools = session.tool_executor.get_available_tools()
        write_enabled = session.tool_executor.has_write_access()
        yolo_mode = session.tool_executor.yolo_mode

        if agent_type == "claude":
            # Use Claude's native SDK with PreToolUse hooks
            # Pass existing session ID for resume if available
            sdk_tools = to_claude_sdk_tools(tools)
            async for event, sdk_session_id in self._claude_client.generate_with_tools_native(
                prompt=prompt,
                tools=sdk_tools,
                system=system,
                write_enabled=write_enabled,
                yolo_mode=yolo_mode,
                session_id=session.claude_sdk_session_id,
            ):
                # Capture and persist SDK session ID if we got a new one
                if sdk_session_id and sdk_session_id != session.claude_sdk_session_id:
                    session.claude_sdk_session_id = sdk_session_id
                    roundtable_storage.update_sdk_session_ids(
                        session_id=session.id,
                        claude_sdk_session_id=sdk_session_id,
                    )
                    logger.info(f"Persisted Claude SDK session ID: {sdk_session_id}")

                yield {"agent": "claude", "event": event, "sdk_session_id": sdk_session_id}

        else:  # gemini
            # Use Google ADK with before_tool_callback
            # Pass existing session ID for resume if available
            adk_tools = to_adk_function_tools(tools, session.tool_executor)
            async for event, gemini_session_id in self._gemini_client.generate_with_tools_native(
                prompt=prompt,
                tools=adk_tools,
                system=system,
                write_enabled=write_enabled,
                yolo_mode=yolo_mode,
                session_id=session.gemini_sdk_session_id,
            ):
                # Capture and persist Gemini session ID if we got a new one
                if gemini_session_id and gemini_session_id != session.gemini_sdk_session_id:
                    session.gemini_sdk_session_id = gemini_session_id
                    roundtable_storage.update_sdk_session_ids(
                        session_id=session.id,
                        gemini_sdk_session_id=gemini_session_id,
                    )
                    logger.info(f"Persisted Gemini SDK session ID: {gemini_session_id}")

                yield {"agent": "gemini", "event": event, "sdk_session_id": gemini_session_id}

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
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

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

    async def get_parallel_responses(
        self,
        session: RoundtableSession,
        message: str,
    ) -> list[RoundtableMessage]:
        """Get responses from both agents in parallel.

        Faster than sequential routing when both agents are needed.
        """
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

        context = session.get_context()
        loop = asyncio.get_event_loop()

        # Run both agents in parallel
        claude_task = loop.run_in_executor(None, self._send_to_agent, "claude", message, context)
        gemini_task = loop.run_in_executor(None, self._send_to_agent, "gemini", message, context)

        results = await asyncio.gather(claude_task, gemini_task, return_exceptions=True)
        responses: list[RoundtableMessage] = []

        for agent_type, result in zip(["claude", "gemini"], results, strict=True):
            if isinstance(result, Exception):
                msg = RoundtableMessage.create(
                    agent_type,  # type: ignore[arg-type]
                    f"[Error: {result!s}]",
                )
            else:
                msg = RoundtableMessage.create(
                    agent_type,  # type: ignore[arg-type]
                    result.content,  # type: ignore[attr-defined]
                    tokens_used=result.usage.get("total_tokens", 0),  # type: ignore[attr-defined]
                    model=result.model,  # type: ignore[attr-defined]
                )
            session.add_message(msg)
            responses.append(msg)

        return responses

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

            # Run async enqueue in a new event loop (we're in sync context)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    queue.enqueue(
                        project_id=project_id,
                        session_id=session_id,
                        agent_type=agent_type,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_output=tool_output,
                    )
                )
            finally:
                loop.close()
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
    ) -> dict:
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
    ) -> dict:
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
            check_reflection_trigger.delay(project_id=project_id)  # type: ignore[operator]
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
