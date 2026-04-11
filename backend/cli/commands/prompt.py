"""Prompt management CLI — CRUD, assignments, import/export."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from ..output import output_error
from ._api_paths import PROMPT_RESTORE_PATH, PROMPT_REVISIONS_PATH
from .memory_options import ChangeReasonOpt, HistoryLimitOpt
from .prompt_api import prompt_api
from .prompt_formatters import (
    format_assigned,
    format_assignments,
    format_created,
    format_deleted,
    format_prompt_detail,
    format_prompt_list,
    format_prompt_restored,
    format_prompt_revisions,
    format_unassigned,
    format_updated,
)
from .prompt_import_export import export_prompts, import_prompts

app = typer.Typer(help="Prompt management (Agent Hub)")


@app.callback(invoke_without_command=True)
def prompt_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        list_prompts(is_global=None)


@app.command("list")
def list_prompts(
    is_global: Annotated[
        bool | None,
        typer.Option("--global/--no-global", help="Filter by global flag"),
    ] = None,
) -> None:
    params: dict[str, Any] = {}
    if is_global is not None:
        params["is_global"] = str(is_global).lower()
    data = prompt_api("GET", "", params=params)
    prompts = data.get("prompts", [])
    format_prompt_list(prompts)


@app.command("get")
def get_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
) -> None:
    p = prompt_api("GET", f"/{slug}")
    format_prompt_detail(p)


@app.command("create")
def create_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
    name: Annotated[str, typer.Argument(help="Display name")],
    file: Annotated[Path, typer.Option("-f", "--file", help="Markdown file path")],
    is_global: Annotated[bool, typer.Option("--global/--no-global", help="Global prompt")] = False,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
) -> None:
    if not file.exists():
        output_error(f"File not found: {file}")
        raise typer.Exit(1)
    content = file.read_text()
    payload: dict[str, Any] = {"slug": slug, "name": name, "content": content, "is_global": is_global}
    if description:
        payload["description"] = description
    p = prompt_api("POST", "", json=payload)
    format_created(slug, content, p)


@app.command("update")
def update_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
    file: Annotated[Path | None, typer.Option("-f", "--file", help="New content file")] = None,
    name: Annotated[str | None, typer.Option("-n", "--name", help="New name")] = None,
    is_global: Annotated[bool | None, typer.Option("--global/--no-global", help="Global flag")] = None,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
    change_reason: ChangeReasonOpt = None,
) -> None:
    payload: dict[str, Any] = {}
    if file:
        if not file.exists():
            output_error(f"File not found: {file}")
            raise typer.Exit(1)
        payload["content"] = file.read_text()
    if name is not None:
        payload["name"] = name
    if is_global is not None:
        payload["is_global"] = is_global
    if description is not None:
        payload["description"] = description
    if not payload:
        output_error("Nothing to update — provide at least one of -f, -n, --global, -d")
        raise typer.Exit(1)
    if change_reason is not None:
        payload["change_reason"] = change_reason
    p = prompt_api("PUT", f"/{slug}", json=payload)
    format_updated(slug, p.get("content", ""), p)


@app.command("revisions")
def revisions_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
    limit: HistoryLimitOpt = 20,
) -> None:
    result = prompt_api(
        "GET",
        PROMPT_REVISIONS_PATH.format(slug=slug).removeprefix("/api/prompts"),
        params={"limit": limit},
        tool_name="st prompt revisions",
    )
    format_prompt_revisions(slug, result)


@app.command("restore")
def restore_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
    revision_id: Annotated[str, typer.Argument(help="Prompt revision UUID to restore")],
    change_reason: ChangeReasonOpt = None,
) -> None:
    payload = {"change_reason": change_reason} if change_reason else {}
    result = prompt_api(
        "POST",
        PROMPT_RESTORE_PATH.format(slug=slug, revision_id=revision_id).removeprefix("/api/prompts"),
        json=payload,
        tool_name="st prompt restore",
    )
    format_prompt_restored(slug, revision_id, result)


@app.command("delete")
def delete_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
) -> None:
    prompt_api("DELETE", f"/{slug}")
    format_deleted(slug)


@app.command("assign")
def assign_prompt(
    agent: Annotated[str, typer.Argument(help="Agent slug")],
    prompt: Annotated[str, typer.Argument(help="Prompt slug")],
    role: Annotated[str, typer.Argument(help="Role (system, guardrail, etc.)")],
    priority: Annotated[int, typer.Option("-p", "--priority", help="Priority (lower = first)")] = 0,
) -> None:
    payload = {"prompt_slug": prompt, "role": role, "priority": priority}
    prompt_api("POST", f"/agents/{agent}/assignments", json=payload)
    format_assigned(agent, prompt, role, priority)


@app.command("unassign")
def unassign_prompt(
    agent: Annotated[str, typer.Argument(help="Agent slug")],
    prompt: Annotated[str, typer.Argument(help="Prompt slug")],
) -> None:
    prompt_api("DELETE", f"/agents/{agent}/assignments/{prompt}")
    format_unassigned(agent, prompt)


@app.command("assignments")
def list_assignments(
    agent: Annotated[str, typer.Argument(help="Agent slug")],
) -> None:
    data = prompt_api("GET", f"/agents/{agent}/assignments")
    assignments = data.get("assignments", [])
    format_assignments(agent, assignments)


# Register import/export commands
app.command("export")(export_prompts)
app.command("import")(import_prompts)
