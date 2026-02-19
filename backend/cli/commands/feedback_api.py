"""API client for Agent Hub feedback system."""

from __future__ import annotations

from typing import Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error
from .memory_api import load_credentials


def feedback_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a request to Agent Hub feedback API with proper authentication."""
    client_id, client_secret, _ = load_credentials()

    headers = {
        "X-Client-Id": client_id,
        "X-Client-Secret": client_secret,
        "X-Request-Source": "st-feedback",
        "X-Source-Client": "st-cli",
        "X-Tool-Name": "st feedback",
    }

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                response = client.get(url, params=params, headers=headers)
            elif method == "PATCH":
                response = client.patch(url, json=json, headers=headers)
            elif method == "DELETE":
                response = client.delete(url, headers=headers)
            else:
                response = client.post(url, json=json, headers=headers)

            if response.status_code >= 400:
                try:
                    err = response.json()
                    detail = err.get("detail") or err.get("message") or response.text
                except Exception:
                    detail = response.text
                output_error(f"{detail}")
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
