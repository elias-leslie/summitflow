"""Complete command - Quick access to Agent Hub /api/complete endpoint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error, output_json

app = typer.Typer(help="Agent Hub completion API")


def _load_credentials() -> tuple[str, str, str]:
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
    client_secret = creds.get("SUMMITFLOW_CLIENT_SECRET") or creds.get("CONSULT_CLIENT_SECRET")
    request_source = creds.get("SUMMITFLOW_REQUEST_SOURCE", "st-complete")

    if not client_id or not client_secret:
        output_error(
            "Missing CONSULT_CLIENT_ID/SECRET or SUMMITFLOW_CLIENT_ID/SECRET in ~/.env.local"
        )
        raise typer.Exit(1)

    return client_id, client_secret, request_source


def _complete(
    agent_slug: str | None,
    message: str,
    project_id: str = "st-cli",
    source_client: str = "st-cli",
    use_memory: bool = True,
    memory_group_id: str | None = None,
    execute_tools: bool = False,
    working_dir: str | None = None,
    timeout: float = 60.0,
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

    payload: dict[str, Any] = {
        "project_id": project_id,
        "messages": [{"role": "user", "content": message}],
    }
    if agent_slug:
        payload["agent_slug"] = agent_slug

    if use_memory:
        payload["use_memory"] = True
    if memory_group_id:
        payload["memory_group_id"] = memory_group_id
    if execute_tools:
        payload["execute_tools"] = True
    if working_dir:
        payload["working_dir"] = working_dir

    agent_hub_url = get_agent_hub_url()

    try:
        with httpx.Client(timeout=timeout) as client:
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

                # Handle agent_slug validation errors with available_agents
                if isinstance(detail, dict):
                    message = detail.get("message", str(detail))
                    available_agents = detail.get("available_agents", [])
                    if available_agents:
                        output_error(message)
                        print("\nAvailable agents:", file=sys.stderr)
                        for agent_info in available_agents:
                            print(f"  {agent_info}", file=sys.stderr)
                        raise typer.Exit(1) from None

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
    agent: Annotated[
        str | None, typer.Option("--agent", "-a", help="Agent slug (required)")
    ] = None,
    project: Annotated[str, typer.Option("--project", "-p", help="Project ID")] = "st-cli",
    source: Annotated[
        str, typer.Option("--source", "-s", help="Source client identifier")
    ] = "st-cli",
    memory: Annotated[bool, typer.Option("--memory", "-m", help="Enable memory injection")] = True,
    memory_group: Annotated[
        str | None, typer.Option("--memory-group", "-g", help="Memory group ID")
    ] = None,
    execute_tools: Annotated[
        bool, typer.Option("--execute-tools", "-x", help="Execute tools (full observability)")
    ] = False,
    working_dir: Annotated[
        str | None, typer.Option("--working-dir", "-w", help="Working directory for tool execution")
    ] = None,
    file: Annotated[
        str | None, typer.Option("--file", "-f", help="Read message from file")
    ] = None,
    timeout: Annotated[
        float, typer.Option("--timeout", "-t", help="Request timeout in seconds")
    ] = 60.0,
    raw: Annotated[bool, typer.Option("--raw", help="Output raw JSON")] = False,
) -> None:
    """Send a completion request to Agent Hub.

    Input priority: message argument > --file > piped stdin.

    Examples:
        st complete "Say hello"
        st complete -a critic --file /tmp/review.txt
        cat prompt.txt | st complete -a reasoner
        st complete "Analyze" -a coder --timeout 300
    """
    if ctx.invoked_subcommand is None:
        resolved_message = _resolve_message(message, file)
        if not resolved_message:
            typer.echo(ctx.get_help())
            return

        result = _complete(
            agent,
            resolved_message,
            project,
            source,
            memory,
            memory_group,
            execute_tools,
            working_dir,
            timeout,
        )

        if raw:
            output_json(result)
        else:
            content = result.get("content", "")
            typer.echo(content)


def _resolve_message(message: str | None, file: str | None) -> str | None:
    """Resolve message from argument, --file, or piped stdin."""
    if message:
        return message

    if file:
        path = Path(file)
        if not path.is_file():
            output_error(f"File not found: {file}")
            raise typer.Exit(1)
        return path.read_text()

    if not sys.stdin.isatty():
        content = sys.stdin.read()
        if content.strip():
            return content

    return None
