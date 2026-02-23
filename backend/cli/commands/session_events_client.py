"""Client functions for fetching session events from Agent Hub and SummitFlow APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import typer

from ..client import APIError, STClient
from ..config import get_agent_hub_url
from ..output import handle_api_error, output_error


def load_credentials() -> tuple[str, str]:
    """Load credentials from ~/.env.local."""
    env_file = Path.home() / ".env.local"
    if not env_file.exists():
        output_error("~/.env.local not found")
        raise typer.Exit(1)

    creds: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            creds[key.strip()] = val.strip()

    client_id = creds.get("SUMMITFLOW_CLIENT_ID") or creds.get("CONSULT_CLIENT_ID")
    request_source = creds.get("SUMMITFLOW_REQUEST_SOURCE", "st-session-events")

    if not client_id:
        output_error(
            "Missing CONSULT_CLIENT_ID or SUMMITFLOW_CLIENT_ID in ~/.env.local"
        )
        raise typer.Exit(1)

    return client_id, request_source


def get_session_events(
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """Fetch session events from Agent Hub directly by session ID."""
    client_id, request_source = load_credentials()

    headers = {
        "X-Client-Id": client_id,
        "X-Request-Source": request_source,
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
    url = f"{agent_hub_url}/api/sessions/{session_id}/events"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)

            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                output_error(f"API error ({response.status_code}): {detail}")
                raise typer.Exit(1) from None

            return cast(dict[str, Any], response.json())
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
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
        )
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
