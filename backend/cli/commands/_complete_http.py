"""HTTP helpers for the complete command."""

from __future__ import annotations

import base64
import mimetypes
import sys
from pathlib import Path
from typing import Any

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error

_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


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
    request_source = creds.get("SUMMITFLOW_REQUEST_SOURCE", "st-complete")
    if not client_id:
        output_error("Missing CONSULT_CLIENT_ID or SUMMITFLOW_CLIENT_ID in ~/.env.local")
        raise typer.Exit(1)
    return client_id, request_source


def handle_error_response(response: httpx.Response) -> None:
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


def build_headers(
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


def encode_image(path: str) -> dict[str, Any]:
    """Read an image file and return an Anthropic-style base64 content block."""
    p = Path(path)
    if not p.is_file():
        output_error(f"Image not found: {path}")
        raise typer.Exit(1)
    suffix = p.suffix.lower()
    media_type = _IMAGE_MIME_TYPES.get(suffix) or mimetypes.guess_type(path)[0] or "image/png"
    data = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def build_payload(
    message: str, project_id: str, agent_slug: str | None,
    memory_group_id: str | None, working_dir: str | None,
    session_id: str | None, thinking_level: str | None,
    trace_id: str | None, use_memory: bool, execute_tools: bool,
    max_turns: int, stream: bool, include_roles: list[str] | None,
    images: list[str] | None = None, timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Build request payload for /api/complete."""
    if images:
        content: list[dict[str, Any]] = [encode_image(img) for img in images]
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
    if timeout_seconds:
        payload["timeout_seconds"] = timeout_seconds
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


def stream_complete(
    agent_hub_url: str, headers: dict[str, str],
    payload: dict[str, Any], timeout: float,
) -> dict[str, Any]:
    """Stream SSE completion, printing content chunks as they arrive."""
    import json

    content_parts: list[str] = []
    last_data: dict[str, Any] = {}
    url = f"{agent_hub_url}/api/complete"
    with httpx.Client(timeout=timeout) as client, client.stream("POST", url, json=payload, headers=headers) as response:
        if response.status_code >= 400:
            response.read()
            handle_error_response(response)
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
    if content_parts:
        sys.stdout.write("\n")
        sys.stdout.flush()
    last_data["content"] = "".join(content_parts)
    return last_data


def _scale_http_timeout(timeout: float, max_turns: int) -> float:
    """Scale HTTP timeout for multi-turn sessions.

    The server enforces per-turn inactivity timeouts internally — the HTTP
    client just needs a generous ceiling so the connection doesn't drop while
    the agent is still making progress across many turns.
    """
    if max_turns > 1:
        return timeout * max_turns + 60
    return timeout + 30


def call_complete(
    agent_slug: str | None, message: str, project_id: str = "st-cli",
    source_client: str = "st-cli", use_memory: bool = True,
    memory_group_id: str | None = None, execute_tools: bool = False,
    working_dir: str | None = None, timeout: float = 300.0,
    skip_cache: bool = False, session_id: str | None = None,
    thinking_level: str | None = None, max_turns: int = 1,
    stream: bool = False, trace_id: str | None = None,
    include_roles: list[str] | None = None,
    images: list[str] | None = None,
) -> dict[str, Any]:
    """Call /api/complete endpoint."""
    from typing import cast

    client_id, request_source = load_credentials()
    agent_hub_url = get_agent_hub_url()
    headers = build_headers(client_id, request_source, source_client, skip_cache)
    payload = build_payload(
        message, project_id, agent_slug, memory_group_id, working_dir,
        session_id, thinking_level, trace_id, use_memory, execute_tools,
        max_turns, stream, include_roles, images, timeout_seconds=timeout,
    )
    read_timeout = _scale_http_timeout(timeout, max_turns)
    http_timeout = httpx.Timeout(connect=5.0, read=read_timeout, write=30.0, pool=30.0)
    max_retries = 2
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            if stream:
                return stream_complete(agent_hub_url, headers, payload, read_timeout)
            with httpx.Client(timeout=http_timeout) as client:
                response = client.post(f"{agent_hub_url}/api/complete", json=payload, headers=headers)
            if response.status_code >= 400:
                handle_error_response(response)
            return cast(dict[str, Any], response.json())
        except httpx.ConnectError as e:
            last_err = e
            if attempt < max_retries:
                import time

                time.sleep(0.5 * attempt)
                continue
            output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
            raise typer.Exit(1) from None
        except typer.Exit:
            raise
        except Exception as e:
            output_error(f"Request failed: {e}")
            raise typer.Exit(1) from None
    # Should not reach here, but handle for safety
    output_error(f"Cannot connect to Agent Hub at {agent_hub_url}: {last_err}")
    raise typer.Exit(1) from None
