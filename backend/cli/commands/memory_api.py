"""API client for Agent Hub memory system."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error


def load_credentials() -> tuple[str, str]:
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
    if not client_id:
        output_error("Missing SUMMITFLOW_CLIENT_ID in ~/.env.local")
        raise typer.Exit(1)

    return client_id, "st-memory"


def _dispatch(client: httpx.Client, method: str, url: str, **kw: Any) -> httpx.Response:
    """Dispatch HTTP request by method."""
    if method == "GET":
        return client.get(url, params=kw.get("params"), headers=kw["headers"])
    if method == "DELETE":
        return client.delete(url, headers=kw["headers"])
    if method == "PUT":
        return client.put(url, json=kw.get("json"), headers=kw["headers"])
    if method == "PATCH":
        return client.patch(url, json=kw.get("json"), headers=kw["headers"])
    return client.post(url, json=kw.get("json"), headers=kw["headers"])


def _check_response(response: httpx.Response, agent_hub_url: str) -> dict[str, Any]:
    """Validate response and return parsed body."""
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
    client_id, request_source = load_credentials()
    headers = {
        "X-Client-Id": client_id,
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
    # Graphiti embedding + Neo4j writes can take 30-60s; generous timeout prevents partial ops.
    timeout = httpx.Timeout(connect=5.0, read=90.0, write=30.0, pool=30.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = _dispatch(client, method, url, params=params, json=json, headers=headers)
            return _check_response(response, agent_hub_url)
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None
