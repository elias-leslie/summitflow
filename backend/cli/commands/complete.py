"""Complete command - Quick access to Agent Hub /api/complete endpoint."""

from __future__ import annotations

import base64
import mimetypes
import sys
from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error, output_json

app = typer.Typer(help="Agent Hub completion API")
_Opt, _Arg = typer.Option, typer.Argument


def _load_credentials() -> tuple[str, str]:
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
    request_source = creds.get("SUMMITFLOW_REQUEST_SOURCE", "st-complete")
    if not client_id:
        output_error("Missing CONSULT_CLIENT_ID or SUMMITFLOW_CLIENT_ID in ~/.env.local")
        raise typer.Exit(1)
    return client_id, request_source


def _handle_error_response(response: httpx.Response) -> None:
    """Handle a non-2xx response, printing diagnostics and exiting."""
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    if not isinstance(detail, dict):
        output_error(f"API error ({response.status_code}): {detail}")
        raise typer.Exit(1) from None
    output_error(detail.get("message", str(detail)))
    agents = detail.get("available_agents", [])
    if agents:
        print("\nAvailable agents:", file=sys.stderr)
        for info in agents:
            print(f"  {info}", file=sys.stderr)
    raise typer.Exit(1) from None


def _build_headers(
    client_id: str, request_source: str, source_client: str, skip_cache: bool
) -> dict[str, str]:
    """Build request headers for /api/complete."""
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Client-Id": client_id,
        "X-Request-Source": request_source,
        "X-Source-Client": source_client,
        "X-Tool-Name": "st complete",
    }
    if skip_cache:
        headers["X-Skip-Cache"] = "true"
    return headers


_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _encode_image(path: str) -> dict[str, Any]:
    """Read an image file and return an Anthropic-style base64 content block."""
    p = Path(path)
    if not p.is_file():
        output_error(f"Image not found: {path}")
        raise typer.Exit(1)
    suffix = p.suffix.lower()
    media_type = _IMAGE_MIME_TYPES.get(suffix) or mimetypes.guess_type(path)[0] or "image/png"
    data = base64.b64encode(p.read_bytes()).decode()
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _build_payload(
    message: str, project_id: str, agent_slug: str | None,
    memory_group_id: str | None, working_dir: str | None,
    session_id: str | None, thinking_level: str | None,
    trace_id: str | None, use_memory: bool, execute_tools: bool,
    max_turns: int, stream: bool, include_roles: list[str] | None,
    images: list[str] | None = None,
) -> dict[str, Any]:
    """Build request payload for /api/complete."""
    # Build content: multimodal blocks when images provided, plain string otherwise
    if images:
        content: list[dict[str, Any]] = [_encode_image(img) for img in images]
        content.append({"type": "text", "text": message})
    else:
        content = message  # type: ignore[assignment]

    payload: dict[str, Any] = {
        "project_id": project_id,
        "messages": [{"role": "user", "content": content}],
    }
    for key, val in [
        ("agent_slug", agent_slug), ("memory_group_id", memory_group_id),
        ("working_dir", working_dir), ("session_id", session_id),
        ("thinking_level", thinking_level), ("trace_id", trace_id),
    ]:
        if val:
            payload[key] = val
    if use_memory:
        payload["use_memory"] = True
    if execute_tools:
        payload["execute_tools"] = True
    if max_turns > 1:
        payload["max_turns"] = max_turns
    if stream:
        payload["stream"] = True
    if include_roles:
        payload["include_roles"] = include_roles
    return payload


def _complete(
    agent_slug: str | None, message: str, project_id: str = "st-cli",
    source_client: str = "st-cli", use_memory: bool = True,
    memory_group_id: str | None = None, execute_tools: bool = False,
    working_dir: str | None = None, timeout: float = 60.0,
    skip_cache: bool = False, session_id: str | None = None,
    thinking_level: str | None = None, max_turns: int = 1,
    stream: bool = False, trace_id: str | None = None,
    include_roles: list[str] | None = None,
    images: list[str] | None = None,
) -> dict[str, Any]:
    """Call /api/complete endpoint."""
    client_id, request_source = _load_credentials()
    agent_hub_url = get_agent_hub_url()
    headers = _build_headers(client_id, request_source, source_client, skip_cache)
    payload = _build_payload(
        message, project_id, agent_slug, memory_group_id, working_dir,
        session_id, thinking_level, trace_id, use_memory, execute_tools,
        max_turns, stream, include_roles, images,
    )
    try:
        if stream:
            return _stream_complete(agent_hub_url, headers, payload, timeout)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{agent_hub_url}/api/complete", json=payload, headers=headers)
        if response.status_code >= 400:
            _handle_error_response(response)
        return cast(dict[str, Any], response.json())
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None


def _stream_complete(
    agent_hub_url: str, headers: dict[str, str],
    payload: dict[str, Any], timeout: float,
) -> dict[str, Any]:
    """Stream SSE completion, printing content chunks as they arrive.

    Returns the final assembled result dict.
    """
    import json

    content_parts: list[str] = []
    last_data: dict[str, Any] = {}

    with httpx.Client(timeout=timeout) as client, client.stream("POST", f"{agent_hub_url}/api/complete", json=payload, headers=headers) as response:
        if response.status_code >= 400:
            response.read()
            _handle_error_response(response)
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                break
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                continue
            last_data = chunk
            text = chunk.get("content", "")
            if text:
                content_parts.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()

    # Print final newline after streaming content
    if content_parts:
        sys.stdout.write("\n")
        sys.stdout.flush()

    # Build a result dict matching non-stream shape
    last_data["content"] = "".join(content_parts)
    return last_data


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


def _output_result(result: dict[str, Any], stream: bool, raw: bool) -> None:
    """Output the completion result to stdout."""
    if stream and not raw:
        # Content already printed during streaming
        return
    if raw:
        output_json(result)
    else:
        typer.echo(result.get("content", ""))


@app.callback(invoke_without_command=True)
def complete_default(
    ctx: typer.Context,
    message: Annotated[str | None, _Arg(help="Message to send")] = None,
    agent: Annotated[str | None, _Opt("--agent", "-a", help="Agent slug")] = None,
    model: Annotated[str | None, _Opt("--model", "-M", help="Model override (e.g. cloudflare/qwen2.5-coder-32b). Uses @mention injection to override agent's default model.")] = None,
    project: Annotated[str, _Opt("--project", "-p", help="Project ID")] = "st-cli",
    source: Annotated[str, _Opt("--source", "-s", help="Source client")] = "st-cli",
    session_id: Annotated[str | None, _Opt("--session", "-S", help="Continue existing session")] = None,
    memory: Annotated[bool, _Opt("--memory", "-m", help="Enable memory injection")] = True,
    memory_group: Annotated[str | None, _Opt("--memory-group", "-g", help="Memory group ID")] = None,
    execute_tools: Annotated[bool, _Opt("--execute-tools", "-x", help="Execute tools")] = False,
    working_dir: Annotated[str | None, _Opt("--working-dir", "-w", help="Working dir")] = None,
    max_turns: Annotated[int, _Opt("--max-turns", "-n", help="Max agentic turns", min=1, max=50)] = 1,
    thinking_level: Annotated[str | None, _Opt("--thinking", help="Thinking level: minimal|low|medium|high|ultrathink")] = None,
    skip_cache: Annotated[bool, _Opt("--skip-cache", help="Bypass response cache")] = False,
    stream: Annotated[bool, _Opt("--stream", help="Stream response via SSE")] = False,
    trace_id: Annotated[str | None, _Opt("--trace", help="Trace ID for event correlation")] = None,
    include_roles: Annotated[str | None, _Opt("--roles", help="Comma-separated prompt roles to include")] = None,
    image: Annotated[list[str] | None, _Opt("--image", "-i", help="Image file path(s) for multimodal input")] = None,
    file: Annotated[str | None, _Opt("--file", "-f", help="Read message from file")] = None,
    timeout: Annotated[float, _Opt("--timeout", "-t", help="Request timeout (s)")] = 60.0,
    raw: Annotated[bool, _Opt("--raw", help="Output raw JSON")] = False,
) -> None:
    """Send a completion request to Agent Hub.

    Input priority: message argument > --file > piped stdin.

    Examples:
        st complete "Say hello"
        st complete -a critic --file /tmp/review.txt
        cat prompt.txt | st complete -a reasoner
        st complete -a coder -x -w /tmp "Run: echo hi"
        st complete -a analyst --thinking medium --skip-cache "Explain CAP theorem"
        st complete -a coder --stream "Write a hello world"
        st complete -a coder -S <session-id> "Continue from last message"
        st complete -a analyst -i /tmp/screenshot.png "Describe this image"
        st complete -a analyst -i img1.png -i img2.png "Compare these"
        st complete -a chat -M cloudflare/qwen2.5-coder-32b "Say hello in 3 words"
    """
    if ctx.invoked_subcommand is not None:
        return
    resolved_message = _resolve_message(message, file)
    if not resolved_message:
        typer.echo(ctx.get_help())
        return
    if model:
        resolved_message = f"@{model} {resolved_message}"
    roles = [r.strip() for r in include_roles.split(",")] if include_roles else None
    result = _complete(
        agent, resolved_message, project, source, memory, memory_group,
        execute_tools, working_dir, timeout, skip_cache, session_id,
        thinking_level, max_turns, stream, trace_id, roles, image or None,
    )
    _output_result(result, stream, raw)
