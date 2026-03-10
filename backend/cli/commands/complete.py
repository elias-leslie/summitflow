"""Complete command - Quick access to Agent Hub /api/complete endpoint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from ..output import output_error, output_json
from ._complete_http import call_complete

app = typer.Typer(help="Agent Hub completion API")
_Opt, _Arg = typer.Option, typer.Argument


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


def _resolve_working_dir(working_dir: str | None, execute_tools: bool) -> str | None:
    """Default tool execution to the caller cwd when no working dir is provided."""
    if working_dir or not execute_tools:
        return working_dir
    return str(Path.cwd())


def _output_result(result: dict[str, Any], stream: bool, raw: bool) -> None:
    """Output the completion result to stdout."""
    if stream and not raw:
        return
    if raw:
        output_json(result)
    else:
        typer.echo(result.get("content", ""))


@app.callback(invoke_without_command=True)
def complete_default(
    ctx: typer.Context,
    message: Annotated[str | None, _Arg(help="Message to send")] = None,
    message_option: Annotated[str | None, _Opt("--message", help="Message to send without relying on positional ordering")] = None,
    agent: Annotated[str | None, _Opt("--agent", "-a", help="Agent slug")] = None,
    model: Annotated[str | None, _Opt("--model", "-M", help="Model override (e.g. cloudflare/qwen2.5-coder-32b). Uses @mention injection to override agent's default model.")] = None,
    project: Annotated[str | None, _Opt("--project", "-p", help="Project ID")] = None,
    source: Annotated[str, _Opt("--source", "-s", help="Source client")] = "st-cli",
    session_id: Annotated[str | None, _Opt("--session", "-S", help="Continue existing session")] = None,
    memory: Annotated[bool, _Opt("--memory", "-m", help="Enable memory injection")] = True,
    memory_group: Annotated[str | None, _Opt("--memory-group", "-g", help="Memory group ID")] = None,
    execute_tools: Annotated[bool, _Opt("--execute-tools", "-x", help="Execute tools")] = False,
    working_dir: Annotated[str | None, _Opt("--working-dir", "-w", help="Working dir")] = None,
    max_turns: Annotated[int, _Opt("--max-turns", "-n", help="Max agentic turns (high limit intentional for long-running autonomous tasks; 300s timeout per turn)", min=1, max=200)] = 1,
    thinking_level: Annotated[str | None, _Opt("--thinking", help="Thinking level: minimal|low|medium|high|ultrathink")] = None,
    skip_cache: Annotated[bool, _Opt("--skip-cache", help="Bypass response cache")] = False,
    stream: Annotated[bool, _Opt("--stream", help="Stream response via SSE")] = False,
    trace_id: Annotated[str | None, _Opt("--trace", help="Trace ID for event correlation")] = None,
    include_roles: Annotated[str | None, _Opt("--roles", help="Comma-separated prompt roles to include")] = None,
    image: Annotated[list[str] | None, _Opt("--image", "-i", help="Image file path(s) for multimodal input")] = None,
    file: Annotated[str | None, _Opt("--file", "-f", help="Read message from file")] = None,
    timeout: Annotated[float, _Opt("--timeout", "-t", help="Per-turn inactivity timeout (s)")] = 300.0,
    raw: Annotated[bool, _Opt("--raw", help="Output raw JSON")] = False,
) -> None:
    """Send a completion request to Agent Hub.

    Input priority: message argument > --file > piped stdin.

    Examples:
        st complete "Say hello"
        st complete -a critic --file /tmp/review.txt
        cat prompt.txt | st complete -a reasoner
        st complete -a coder -x -w /tmp "Run: echo hi"
        st complete -a coder --stream "Write a hello world"
    """
    if ctx.invoked_subcommand is not None:
        return
    resolved_message = _resolve_message(message_option or message, file)
    if not resolved_message:
        typer.echo(ctx.get_help())
        return
    if model:
        resolved_message = f"@{model} {resolved_message}"
    roles = [r.strip() for r in include_roles.split(",")] if include_roles else None
    if not project:
        from ..config import get_config_optional

        cfg = get_config_optional()
        project = cfg.project_id or "st-cli"
    resolved_working_dir = _resolve_working_dir(working_dir, execute_tools)
    result = call_complete(
        agent, resolved_message, project, source, memory, memory_group,
        execute_tools, resolved_working_dir, timeout, skip_cache, session_id,
        thinking_level, max_turns, stream, trace_id, roles, image or None,
    )
    _output_result(result, stream, raw)
