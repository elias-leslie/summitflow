"""Client functions for fetching session events from Agent Hub and SummitFlow APIs."""

from __future__ import annotations

from typing import Any, cast

import httpx
import typer

from ..client import APIError, STClient
from ..config import get_agent_hub_url
from ..lib.credentials import load_credentials
from ..output import handle_api_error, output_error
from ._http_errors import parse_error_detail, raise_connect_error, raise_timeout_error

# HTTP headers
_HEADER_CLIENT_ID = "X-Client-Id"
_HEADER_REQUEST_SOURCE = "X-Request-Source"

# API paths
_SESSIONS_EVENTS_PATH = "/api/sessions/{session_id}/events"

# HTTP config
_HTTP_TIMEOUT = 30.0


def _check_response(response: httpx.Response) -> dict[str, Any]:
    """Validate HTTP response and return parsed JSON body."""
    if response.status_code < 400:
        return cast(dict[str, Any], response.json())
    detail = parse_error_detail(response)
    output_error(f"API error ({response.status_code}): {detail}")
    raise typer.Exit(1) from None


def get_session_events(
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """Fetch session events from Agent Hub directly by session ID."""
    client_id, request_source = load_credentials(default_source="st-session-events")

    headers = {
        _HEADER_CLIENT_ID: client_id,
        _HEADER_REQUEST_SOURCE: request_source,
    }

    params: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}{_SESSIONS_EVENTS_PATH.format(session_id=session_id)}"

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(url, headers=headers, params=params)
        return _check_response(response)
    except httpx.ConnectError as e:
        raise_connect_error("Agent Hub", agent_hub_url, e)
    except httpx.TimeoutException as e:
        raise_timeout_error("Agent Hub", agent_hub_url, _HTTP_TIMEOUT, e)
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None


def get_task_events(
    task_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 500,
    include_history: bool = False,
) -> dict[str, Any]:
    """Fetch agent events for a task via SummitFlow observability API."""
    client = STClient()
    try:
        return client.get_task_agent_events(
            task_id,
            event_type=event_type,
            turn=turn,
            page=page,
            page_size=page_size,
            include_history=include_history,
        )
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
