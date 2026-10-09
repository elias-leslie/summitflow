"""Agent command - tool-loop Agent Hub runs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from agent_hub_st.completion import call_complete
from agent_hub_st.completion import completion_failed as _completion_failed
from agent_hub_st.completion import resolve_message as _resolve_message

from ..client import APIError, STClient
from ..config import get_config_optional
from ..output import handle_api_error, output_json
from ._session_resolver import resolve_session_id

app = typer.Typer(help="Run Agent Hub agents with tools", no_args_is_help=True)

NORMAL_TERMINATION_REASONS = {"streaming_one_shot_closed"}


def _project(project: str | None) -> str:
    if project:
        return project
    cfg = get_config_optional()
    return cfg.project_id or "st-cli"


def _roles(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _working_dir(value: str | None) -> str:
    return value or str(Path.cwd())


def _status_from_result(result: dict[str, Any]) -> str:
    if result.get("error"):
        return "error"
    finish = str(result.get("finish_reason") or "")
    if finish in {"error", "max_turns"}:
        return finish
    content = result.get("content")
    if isinstance(content, str) and content.startswith("Error:"):
        return "error"
    return "ok"


def _error_lines_from_content(content: Any) -> list[str]:
    if not isinstance(content, str):
        return []
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return [
        line[:240]
        for line in lines
        if any(marker in line.lower() for marker in ("error", "failed", "traceback", "exception"))
    ][:5]


def _error_lines_from_progress(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for entry in result.get("progress_log") or []:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "")
        message = str(entry.get("message") or "")
        failed_tools = [
            str(tool.get("name") or "?")
            for tool in (entry.get("tool_results") or [])
            if isinstance(tool, dict) and tool.get("is_error")
        ]
        if status == "error" or failed_tools:
            suffix = f" tools={','.join(failed_tools)}" if failed_tools else ""
            lines.append(f"{status or 'error'}: {message[:200]}{suffix}")
    return lines[:5]


def _emit_agent_summary(result: dict[str, Any]) -> None:
    status = _status_from_result(result)
    parts = [
        f"AGENT status={status}",
        f"session={result.get('session_id') or '-'}",
        f"model={result.get('model_used') or result.get('model') or '-'}",
        f"turns={result.get('turns') or 1}",
        f"tools={result.get('tool_calls_count') or 0}",
    ]
    finish = result.get("finish_reason")
    if finish:
        parts.append(f"finish={finish}")
    print(" ".join(parts), file=sys.stderr)
    if status != "ok" or result.get("error_summary"):
        errors = []
        if result.get("error"):
            errors.append(str(result["error"])[:240])
        summary = result.get("error_summary")
        if isinstance(summary, dict):
            for item in summary.get("items") or []:
                if isinstance(item, dict) and item.get("message"):
                    tool = f"{item.get('tool')}: " if item.get("tool") else ""
                    errors.append(f"{item.get('kind') or 'error'}: {tool}{str(item['message'])[:220]}")
        errors.extend(_error_lines_from_progress(result))
        errors.extend(_error_lines_from_content(result.get("content")))
        if errors:
            print("AGENT_ERRORS", file=sys.stderr)
            seen: set[str] = set()
            for line in errors:
                if line in seen:
                    continue
                seen.add(line)
                print(f"- {line}", file=sys.stderr)


@app.command("run")
def run_agent(
    message: Annotated[str | None, typer.Argument(help="Message to send")] = None,
    message_option: Annotated[str | None, typer.Option("--message", help="Message to send without relying on positional ordering")] = None,
    agent: Annotated[str | None, typer.Option("--agent", "-a", help="Exact Agent Hub agent slug")] = None,
    model: Annotated[str | None, typer.Option("--model", "-M", help="Manual model override via Agent Hub @mention")] = None,
    project: Annotated[str | None, typer.Option("--project", "-P", "-p", help="Project ID")] = None,
    source: Annotated[str, typer.Option("--source", "-s", help="Source client")] = "st-cli",
    session_id: Annotated[str | None, typer.Option("--session", "-S", help="Continue existing session")] = None,
    parent_session_id: Annotated[str | None, typer.Option("--parent-session", help="Parent session for child-lane tracking")] = None,
    memory: Annotated[bool, typer.Option("--memory/--no-memory", "-m", help="Enable memory injection")] = True,
    memory_group: Annotated[str | None, typer.Option("--memory-group", "-g", help="Memory group ID")] = None,
    working_dir: Annotated[str | None, typer.Option("--working-dir", "-w", help="Working dir; defaults to caller cwd")] = None,
    read_only: Annotated[bool, typer.Option("--read-only", help="Mark run as read-only for ownership/lane views")] = False,
    task_type: Annotated[str | None, typer.Option("--task-type", help="Optional task type label")] = None,
    thinking_level: Annotated[str | None, typer.Option("--thinking", help="Thinking level: minimal|low|medium|high|ultrathink")] = None,
    skip_cache: Annotated[bool, typer.Option("--skip-cache", help="Bypass response cache")] = False,
    stream: Annotated[bool, typer.Option("--stream", help="Stream response via SSE")] = False,
    trace_id: Annotated[str | None, typer.Option("--trace", help="Trace ID for event correlation")] = None,
    include_roles: Annotated[str | None, typer.Option("--roles", help="Comma-separated prompt roles to include")] = None,
    image: Annotated[list[str] | None, typer.Option("--image", "-i", help="Image file path(s) for multimodal input")] = None,
    audio: Annotated[list[str] | None, typer.Option("--audio", "-A", help="Audio file path(s): WAV, MP3, AIFF, AAC, OGG, or FLAC")] = None,
    file: Annotated[str | None, typer.Option("--file", "-f", help="Read message from file")] = None,
    timeout: Annotated[float | None, typer.Option("--timeout", "-t", help="Optional manual smoke-test/read ceiling in seconds. Omit for normal agent work.")] = None,
    raw: Annotated[bool, typer.Option("--raw", help="Output raw JSON")] = False,
) -> None:
    """Run an Agent Hub agent in real tool-loop mode."""
    resolved_message = _resolve_message(message_option or message, file)
    if not resolved_message:
        typer.echo("Missing message. Provide argument, --message, --file, or stdin.", err=True)
        raise typer.Exit(1)
    if not agent:
        typer.echo("Missing --agent exact Agent Hub slug.", err=True)
        raise typer.Exit(1)
    if model:
        resolved_message = f"@{model} {resolved_message}"

    result = call_complete(
        agent_slug=agent,
        message=resolved_message,
        project_id=_project(project),
        source_client=source,
        use_memory=memory,
        memory_group_id=memory_group,
        execute_tools=True,
        working_dir=_working_dir(working_dir),
        timeout=timeout,
        skip_cache=skip_cache,
        session_id=session_id,
        thinking_level=thinking_level,
        max_turns=None,
        stream=stream,
        trace_id=trace_id,
        include_roles=_roles(include_roles),
        task_type=task_type,
        images=image or None,
        audios=audio or None,
        parent_session_id=parent_session_id,
        read_only=read_only,
        tool_name="st agent",
    )
    status = _status_from_result(result)
    _emit_agent_summary(result)
    if raw:
        output_json(result)
    elif not stream:
        typer.echo(result.get("content", ""))
    if _completion_failed(result) or status != "ok":
        raise typer.Exit(1)


@app.command("status")
def status_agent(session_id: str, raw: Annotated[bool, typer.Option("--raw")] = False) -> None:
    """Show compact status for an agent session.

    Accepts the short ID printed by ``st sessions list`` as well as the full
    UUID; prefixes are resolved before the API call.
    """
    client = STClient(require_project=False)
    resolved_id = resolve_session_id(session_id, client)
    try:
        session = client.get_session(resolved_id)
    except APIError as e:
        handle_api_error(e)
        return
    if raw:
        output_json(session)
        return
    live = session.get("live_activity") if isinstance(session, dict) else None
    live = live if isinstance(live, dict) else {}
    print(
        "AGENT_SESSION "
        f"session={session.get('id', session_id)} "
        f"project={session.get('project_id', '-')} "
        f"status={session.get('status', '-')} "
        f"agent={session.get('agent_slug', '-')} "
        f"phase={live.get('phase', '-')} "
        f"health={live.get('status', session.get('health_detail', '-'))} "
        f"summary={str(live.get('summary') or '-')[:180]}"
    )
    termination = live.get("termination_reason")
    if termination and termination not in NORMAL_TERMINATION_REASONS:
        print(f"AGENT_ERROR {str(termination)[:300]}")
    tool_error = live.get("last_tool_error_excerpt")
    if tool_error:
        print(f"AGENT_TOOL_ERROR {str(tool_error)[:300]}")


@app.command("stop")
def stop_agent(session_id: str) -> None:
    """Close an active agent session.

    Accepts the short ID printed by ``st sessions list`` as well as the full
    UUID; prefixes are resolved before the API call.
    """
    client = STClient(require_project=False)
    resolved_id = resolve_session_id(session_id, client)
    try:
        output_json(client.close_session(resolved_id))
    except APIError as e:
        handle_api_error(e)
