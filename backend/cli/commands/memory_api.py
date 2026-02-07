"""API client for Agent Hub memory system."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error


def load_credentials() -> tuple[str, str, str]:
    """Load credentials from ~/.env.local."""
    env_file = Path.home() / ".env.local"
    if not env_file.exists():
        output_error("~/.env.local not found - required for Agent Hub authentication")
        raise typer.Exit(1)

    creds: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            creds[key.strip()] = val.strip()

    client_id = creds.get("SUMMITFLOW_CLIENT_ID")
    client_secret = creds.get("SUMMITFLOW_CLIENT_SECRET")
    request_source = "st-memory"

    if not client_id or not client_secret:
        output_error("Missing SUMMITFLOW_CLIENT_ID/SECRET in ~/.env.local")
        raise typer.Exit(1)

    return client_id, client_secret, request_source


def agent_hub_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    scope: str = "global",
    scope_id: str | None = None,
    tool_name: str = "st memory",
) -> dict[str, Any]:
    """Make a request to Agent Hub API with proper authentication."""
    client_id, client_secret, request_source = load_credentials()

    headers = {
        "X-Client-Id": client_id,
        "X-Client-Secret": client_secret,
        "X-Request-Source": request_source,
        "X-Source-Client": "st-cli",
        "X-Tool-Name": tool_name,
    }
    if scope != "global":
        headers["X-Memory-Scope"] = scope
    if scope_id:
        headers["X-Scope-Id"] = scope_id

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                response = client.get(url, params=params, headers=headers)
            elif method == "DELETE":
                response = client.delete(url, headers=headers)
            elif method == "PUT":
                response = client.put(url, json=json, headers=headers)
            elif method == "PATCH":
                response = client.patch(url, json=json, headers=headers)
            else:
                response = client.post(url, json=json, headers=headers)

            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                output_error(f"API error ({response.status_code}): {detail}")
                raise typer.Exit(1) from None

            if response.status_code == 204:
                return {"success": True}

            return cast(dict[str, Any], response.json())
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None
