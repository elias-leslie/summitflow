"""Complete command - Quick access to Agent Hub /api/complete endpoint."""

from __future__ import annotations

from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error, output_json

app = typer.Typer(help="Agent Hub completion API")


def _load_credentials() -> tuple[str, str, str]:
    """Load credentials from ~/.env.local."""
    from pathlib import Path

    env_file = Path.home() / ".env.local"
    if not env_file.exists():
        output_error("~/.env.local not found")
        raise typer.Exit(1)

    creds: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            creds[key.strip()] = val.strip()

    client_id = creds.get("CONSULT_CLIENT_ID") or creds.get("SUMMITFLOW_CLIENT_ID")
    client_secret = creds.get("CONSULT_CLIENT_SECRET") or creds.get("SUMMITFLOW_CLIENT_SECRET")
    request_source = creds.get("CONSULT_REQUEST_SOURCE", "st-complete")

    if not client_id or not client_secret:
        output_error(
            "Missing CONSULT_CLIENT_ID/SECRET or SUMMITFLOW_CLIENT_ID/SECRET in ~/.env.local"
        )
        raise typer.Exit(1)

    return client_id, client_secret, request_source


def _complete(
    agent_slug: str,
    message: str,
    project_id: str = "st-cli",
    source_client: str = "st-cli",
) -> dict[str, Any]:
    """Call /api/complete endpoint."""
    client_id, client_secret, request_source = _load_credentials()

    headers = {
        "Content-Type": "application/json",
        "X-Client-Id": client_id,
        "X-Client-Secret": client_secret,
        "X-Request-Source": request_source,
        "X-Source-Client": source_client,
        "X-Tool-Name": "st complete",
    }

    payload = {
        "agent_slug": agent_slug,
        "project_id": project_id,
        "messages": [{"role": "user", "content": message}],
    }

    agent_hub_url = get_agent_hub_url()

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{agent_hub_url}/api/complete",
                json=payload,
                headers=headers,
            )

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


@app.callback(invoke_without_command=True)
def complete_default(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Argument(help="Message to send")] = None,
    agent: Annotated[str, typer.Option("--agent", "-a", help="Agent slug")] = "validator",
    project: Annotated[str, typer.Option("--project", "-p", help="Project ID")] = "st-cli",
    source: Annotated[
        str, typer.Option("--source", "-s", help="Source client identifier")
    ] = "st-cli",
    raw: Annotated[bool, typer.Option("--raw", help="Output raw JSON")] = False,
) -> None:
    """Send a completion request to Agent Hub.

    Examples:
        st complete "Say hello"
        st complete "Analyze this" -a reasoner
        st complete "Test" -s st-cli-test --raw
    """
    if ctx.invoked_subcommand is None:
        if not message:
            typer.echo(ctx.get_help())
            return

        result = _complete(agent, message, project, source)

        if raw:
            output_json(result)
        else:
            content = result.get("content", "")
            typer.echo(content)
