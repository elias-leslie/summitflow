"""Agent management CLI for Agent Hub-backed settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from ..output import output_error, output_json
from .agents_api import agent_preview_api, agents_api

app = typer.Typer(help="Agent management (Agent Hub)")


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        output_error(f"{label} file not found: {path}")
        raise typer.Exit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        output_error(f"Invalid JSON in {label} file: {exc}")
        raise typer.Exit(1) from exc
    if not isinstance(data, dict):
        output_error(f"{label} file must contain a JSON object")
        raise typer.Exit(1)
    return data


def _load_text_file(path: Path, label: str) -> str:
    if not path.exists():
        output_error(f"{label} file not found: {path}")
        raise typer.Exit(1)
    return path.read_text(encoding="utf-8")


def _print_agent(agent: dict[str, Any]) -> None:
    print(
        f"{agent['slug']} | primary={agent['primary_model_id']} | "
        f"fallbacks={len(agent.get('fallback_models') or [])} | version={agent['version']}"
    )
    print(
        f"  active={agent['is_active']} coding={agent['is_coding_agent']} "
        f"thinking={agent.get('thinking_level') or '-'} temp={agent['temperature']}"
    )
    print(f"  memory_config={json.dumps(agent.get('memory_config'), sort_keys=True)}")


@app.callback(invoke_without_command=True)
def agents_default(ctx: typer.Context) -> None:
    """List agents by default."""
    if ctx.invoked_subcommand is None:
        list_agents()


@app.command("list")
def list_agents(
    active_only: Annotated[bool, typer.Option("--active-only/--all")] = True,
    coding_only: Annotated[bool | None, typer.Option("--coding-only/--non-coding")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
) -> None:
    """List agents."""
    params: dict[str, Any] = {
        "active_only": str(active_only).lower(),
        "limit": limit,
        "offset": offset,
    }
    if coding_only is not None:
        params["is_coding_agent"] = str(coding_only).lower()
    result = agents_api("GET", "", params=params)
    output_json(result)


@app.command("get")
def get_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
) -> None:
    """Get one agent by slug."""
    agent = agents_api("GET", f"/{slug}")
    _print_agent(agent)


@app.command("preview")
def preview_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    mode: Annotated[str, typer.Option("--mode", "-m", help="Preview mode: chat, heartbeat, wake, review")] = "chat",
    project: Annotated[str | None, typer.Option("--project", "-P", help="Optional project scope")] = None,
    phase: Annotated[str | None, typer.Option("--phase", help="Optional phase/event hint")] = None,
    prompt_input: Annotated[str | None, typer.Option("--input", help="Optional task input placeholder")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON response")] = False,
    full_context_only: Annotated[bool, typer.Option("--full-context-only", help="Print only the effective full context")] = False,
) -> None:
    """Show the effective runtime prompt/context preview for an agent."""
    preview = agent_preview_api(
        slug,
        task_type=mode,
        project_id=project,
        phase=phase,
        prompt_input=prompt_input,
    )
    if as_json:
        output_json(preview)
        return

    full_context = preview.get("full_context") or preview.get("combined_prompt") or ""
    if full_context_only:
        print(full_context)
        return

    print(
        f"{preview.get('name', slug)} preview | "
        f"mode={preview.get('task_type') or mode} | "
        f"sections={len(preview.get('sections') or [])} | "
        f"mandates={preview.get('mandate_count', 0)} | "
        f"guardrails={preview.get('guardrail_count', 0)}"
    )
    if preview.get("memory_query"):
        print(f"memory_query={preview['memory_query']}")

    for section in preview.get("sections") or []:
        print(
            "\n"
            f"=== {section.get('label', 'Section')} | "
            f"{section.get('placement', 'system')} | "
            f"{section.get('source_kind', 'unknown')} | "
            f"{section.get('source_id', '-')}"
            f" | {section.get('estimated_tokens', 0)} tok ==="
        )
        print(section.get("content", ""))

    if preview.get("loaded_memory_uuids"):
        print("\n=== Loaded Memory UUIDs ===")
        for uuid in preview["loaded_memory_uuids"]:
            print(uuid)

    print("\n=== Full Context ===")
    print(full_context)


@app.command("update")
def update_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    primary_model: Annotated[str | None, typer.Option("--primary-model")] = None,
    temperature: Annotated[float | None, typer.Option("--temperature", min=0.0, max=2.0)] = None,
    thinking_level: Annotated[str | None, typer.Option("--thinking-level")] = None,
    active: Annotated[bool | None, typer.Option("--active/--inactive")] = None,
    coding_agent: Annotated[bool | None, typer.Option("--coding-agent/--non-coding-agent")] = None,
    fallback_model: Annotated[list[str] | None, typer.Option("--fallback-model")] = None,
    system_prompt_file: Annotated[Path | None, typer.Option("--system-prompt-file")] = None,
    memory_config_file: Annotated[Path | None, typer.Option("--memory-config-file")] = None,
    clear_memory_config: Annotated[bool, typer.Option("--clear-memory-config")] = False,
    change_reason: Annotated[str | None, typer.Option("--change-reason")] = None,
) -> None:
    """Update an agent using the Agent Hub API."""
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description
    if primary_model is not None:
        payload["primary_model_id"] = primary_model
    if temperature is not None:
        payload["temperature"] = temperature
    if thinking_level is not None:
        payload["thinking_level"] = thinking_level
    if active is not None:
        payload["is_active"] = active
    if coding_agent is not None:
        payload["is_coding_agent"] = coding_agent
    if fallback_model is not None:
        payload["fallback_models"] = fallback_model
    if system_prompt_file is not None:
        payload["system_prompt"] = _load_text_file(system_prompt_file, "System prompt")
    if memory_config_file is not None and clear_memory_config:
        output_error("Use either --memory-config-file or --clear-memory-config, not both")
        raise typer.Exit(1)
    if memory_config_file is not None:
        payload["memory_config"] = _load_json_file(memory_config_file, "Memory config")
    if clear_memory_config:
        payload["memory_config"] = None
    if change_reason is not None:
        payload["change_reason"] = change_reason

    if not payload:
        output_error("Nothing to update. Provide at least one update flag.")
        raise typer.Exit(1)

    updated = agents_api("PUT", f"/{slug}", json=payload)
    _print_agent(updated)
