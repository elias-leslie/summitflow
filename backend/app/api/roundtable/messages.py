"""Message handling endpoints for roundtable."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...services.roundtable import (
    RoundtableMessage,
    current_session_id,
    get_roundtable_service,
    permission_manager,
)
from ...storage import roundtable as roundtable_storage
from .helpers import get_preview, restore_session_from_db
from .models import (
    MessageRequest,
    MessageResponse,
    PermissionResolution,
    PermissionResolutionResponse,
    SendMessageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format an SSE event.

    Args:
        event_type: Event type (user_message, agent_start, agent_chunk, agent_complete, done, error)
        data: Event data dict

    Returns:
        Formatted SSE event string
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/permissions/{permission_id}",
    response_model=PermissionResolutionResponse,
)
async def resolve_permission(
    project_id: str,
    session_id: str,
    permission_id: str,
    request: PermissionResolution,
):
    """Resolve a pending permission request.

    Called by the frontend when the user approves or denies a write tool operation.
    The pending permission must exist and not have timed out.

    Args:
        project_id: Project ID (for URL consistency)
        session_id: Session ID (for URL consistency)
        permission_id: The ID of the pending permission to resolve
        request: Contains the approval decision

    Returns:
        Success response with status and approved value

    Raises:
        HTTPException: 404 if permission not found or expired
    """
    success = permission_manager.resolve(permission_id, request.approved)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Permission request not found or expired",
        )

    logger.info(
        "permission_resolved",
        extra={
            "permission_id": permission_id,
            "session_id": session_id,
            "approved": request.approved,
        },
    )

    return PermissionResolutionResponse(
        status="resolved",
        approved=request.approved,
    )


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
)
async def send_message(
    project_id: str,
    session_id: str,
    request: MessageRequest,
):
    """Send a message in a roundtable session."""
    service = get_roundtable_service()

    # Get or recreate session
    session = service.get_session(session_id)
    if not session:
        session = restore_session_from_db(service, session_id, project_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    # Route message to agents
    responses = []
    async for response in service.route_message_async(session, request.message, request.target):
        responses.append(response)

    # Get the user message (second to last in session)
    user_msg = session.messages[-len(responses) - 1]

    # Persist to database
    messages_data = [
        {
            "id": m.id,
            "agent": m.agent,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "tokens_used": m.tokens_used,
            "model": m.model,
        }
        for m in session.messages
    ]
    roundtable_storage.save_session(
        session_id=session_id,
        project_id=project_id,
        mode=session.mode,
        messages=messages_data,
        generated_features=None,  # Don't overwrite existing features
    )

    return SendMessageResponse(
        user_message=MessageResponse(
            id=user_msg.id,
            agent=user_msg.agent,
            content=user_msg.content,
            timestamp=user_msg.timestamp.isoformat(),
            tokens_used=user_msg.tokens_used,
            model=user_msg.model,
        ),
        responses=[
            MessageResponse(
                id=r.id,
                agent=r.agent,
                content=r.content,
                timestamp=r.timestamp.isoformat(),
                tokens_used=r.tokens_used,
                model=r.model,
            )
            for r in responses
        ],
    )


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/messages/stream",
)
async def stream_message(
    project_id: str,
    session_id: str,
    request_body: MessageRequest,
    request: Request,
) -> StreamingResponse:
    """Send a message and stream agent responses via Server-Sent Events.

    Events emitted:
    - user_message: Confirms user message was received
    - agent_start: Agent is about to respond (includes agent name)
    - agent_complete: Agent response complete (includes full content)
    - done: All agents have responded
    - error: An error occurred

    Args:
        project_id: Project ID
        session_id: Session ID
        request_body: Message request with message and target
        request: FastAPI request (for disconnect detection)

    Returns:
        StreamingResponse with text/event-stream content type
    """
    service = get_roundtable_service()

    # Get or recreate session
    session = service.get_session(session_id)
    if not session:
        session = restore_session_from_db(service, session_id, project_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for roundtable messages."""

        # Set the session_id context for permission callbacks
        current_session_id.set(session_id)

        logger.info("sse_roundtable_stream_started", extra={"session_id": session_id})

        try:
            # First, add user message to session and emit confirmation

            user_msg = RoundtableMessage.create("user", request_body.message)
            session.add_message(user_msg)

            yield _sse_event(
                "user_message",
                {
                    "id": user_msg.id,
                    "content": request_body.message,
                    "timestamp": user_msg.timestamp.isoformat(),
                },
            )

            responses = []
            agents_to_query = []
            if request_body.target in ("claude", "both"):
                agents_to_query.append("claude")
            if request_body.target in ("gemini", "both"):
                agents_to_query.append("gemini")

            context = session.get_context()

            for agent_type in agents_to_query:
                # Check for client disconnect
                if await request.is_disconnected():
                    logger.info("sse_client_disconnected", extra={"session_id": session_id})
                    break

                # Emit agent start
                yield _sse_event("agent_start", {"agent": agent_type})

                try:
                    # Send keepalive ping while waiting for agent
                    # Run agent call in background, send pings every 10 seconds
                    import functools

                    loop = asyncio.get_event_loop()

                    # Use functools.partial to pass session as kwarg
                    agent_func = functools.partial(
                        service._send_to_agent,
                        agent_type,
                        request_body.message,
                        context,
                        session=session,
                    )
                    agent_task = loop.run_in_executor(None, agent_func)

                    # Track which permissions we've already emitted events for
                    emitted_permissions: set[str] = set()

                    # Send keepalive pings and check for permission requests while waiting
                    while True:
                        try:
                            llm_response = await asyncio.wait_for(
                                asyncio.shield(agent_task), timeout=1.0
                            )
                            break  # Got response
                        except TimeoutError:
                            # Check for pending permissions for this session
                            pending = permission_manager.get_session_pending(session_id)
                            for perm in pending:
                                if perm.id not in emitted_permissions:
                                    # Emit permission_request SSE event
                                    yield _sse_event(
                                        "permission_request",
                                        {
                                            "permission_id": perm.id,
                                            "tool_name": perm.tool_name,
                                            "params": perm.tool_args,
                                            "preview": get_preview(perm.tool_name, perm.tool_args),
                                            "agent": agent_type,
                                        },
                                    )
                                    emitted_permissions.add(perm.id)
                                    logger.info(
                                        "sse_permission_request_emitted",
                                        extra={
                                            "session_id": session_id,
                                            "permission_id": perm.id,
                                            "tool_name": perm.tool_name,
                                        },
                                    )

                            # Send keepalive every 10 iterations (10 seconds)
                            if len(emitted_permissions) == 0:
                                # Only send keepalive if no permissions pending
                                # (permission dialog shows its own activity)
                                yield _sse_event("keepalive", {"agent": agent_type})

                            if await request.is_disconnected():
                                logger.info(
                                    "sse_client_disconnected_during_agent",
                                    extra={"session_id": session_id, "agent": agent_type},
                                )
                                # Auto-deny any pending permissions for this session
                                denied_count = permission_manager.deny_session_pending(session_id)
                                if denied_count > 0:
                                    logger.info(
                                        "sse_permissions_auto_denied_on_disconnect",
                                        extra={"session_id": session_id, "count": denied_count},
                                    )
                                return

                    # Create and store the message
                    msg = RoundtableMessage.create(
                        agent_type,  # type: ignore
                        llm_response.content,
                        tokens_used=llm_response.usage.get("total_tokens", 0),
                        model=llm_response.model,
                    )
                    session.add_message(msg)
                    responses.append(msg)

                    # Update context for next agent
                    context = session.get_context()

                    # Emit agent complete with full response
                    yield _sse_event(
                        "agent_complete",
                        {
                            "id": msg.id,
                            "agent": msg.agent,
                            "content": msg.content,
                            "timestamp": msg.timestamp.isoformat(),
                            "tokens_used": msg.tokens_used,
                            "model": msg.model,
                        },
                    )

                except Exception as agent_error:
                    logger.error(
                        "sse_agent_error",
                        extra={
                            "session_id": session_id,
                            "agent": agent_type,
                            "error": str(agent_error),
                        },
                    )
                    # Create error message for this agent
                    error_msg = RoundtableMessage.create(
                        agent_type,  # type: ignore
                        f"[Error: {agent_error!s}]",
                    )
                    session.add_message(error_msg)
                    responses.append(error_msg)

                    yield _sse_event(
                        "agent_complete",
                        {
                            "id": error_msg.id,
                            "agent": error_msg.agent,
                            "content": error_msg.content,
                            "timestamp": error_msg.timestamp.isoformat(),
                            "tokens_used": 0,
                            "model": None,
                        },
                    )
                    # Continue to next agent even if this one failed

            # Persist to database
            messages_data = [
                {
                    "id": m.id,
                    "agent": m.agent,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "tokens_used": m.tokens_used,
                    "model": m.model,
                }
                for m in session.messages
            ]
            roundtable_storage.save_session(
                session_id=session_id,
                project_id=project_id,
                mode=session.mode,
                messages=messages_data,
                generated_features=None,
            )

            # Emit done event
            yield _sse_event(
                "done",
                {
                    "session_id": session_id,
                    "response_count": len(responses),
                },
            )
            logger.info(
                "sse_roundtable_stream_completed",
                extra={"session_id": session_id, "response_count": len(responses)},
            )

        except Exception as e:
            logger.error(
                "sse_roundtable_stream_error",
                extra={"session_id": session_id, "error": str(e)},
            )
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
