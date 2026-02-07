"""Prompt management CLI — CRUD, assignments, import/export."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from ..output import is_compact, output_error, output_json
from .memory_api import agent_hub_request

app = typer.Typer(help="Prompt management (Agent Hub)")


def _api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    return agent_hub_request(method, f"/api/prompts{path}", tool_name="st prompt", **kwargs)


def _line_count(content: str) -> int:
    return content.count("\n") + (1 if content and not content.endswith("\n") else 0)


def _print_prompt_row(p: dict[str, Any]) -> None:
    slug = p["slug"]
    name = p["name"]
    g = "Y" if p.get("is_global") else "N"
    lines = _line_count(p.get("content", ""))
    print(f"  {slug:<20s} {name:<24s} {g}   {lines}L")


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
    data = _api("GET", "", params=params)
    prompts = data.get("prompts", [])
    if is_compact():
        print(f"PROMPTS[{len(prompts)}]")
        for p in prompts:
            _print_prompt_row(p)
    else:
        output_json(data)


@app.command("get")
def get_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
) -> None:
    p = _api("GET", f"/{slug}")
    if is_compact():
        g = "Y" if p.get("is_global") else "N"
        lines = _line_count(p.get("content", ""))
        print(f"PROMPT:{p['slug']}|{p['name']}|{g}|{lines}L")
        print(p.get("content", ""))
    else:
        output_json(p)


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
    p = _api("POST", "", json=payload)
    if is_compact():
        lines = _line_count(content)
        print(f"CREATED:{slug}|{lines}L")
    else:
        output_json(p)


@app.command("update")
def update_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
    file: Annotated[Path | None, typer.Option("-f", "--file", help="New content file")] = None,
    name: Annotated[str | None, typer.Option("-n", "--name", help="New name")] = None,
    is_global: Annotated[bool | None, typer.Option("--global/--no-global", help="Global flag")] = None,
    description: Annotated[str | None, typer.Option("-d", "--description")] = None,
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
    p = _api("PUT", f"/{slug}", json=payload)
    if is_compact():
        lines = _line_count(p.get("content", ""))
        print(f"UPDATED:{slug}|{lines}L")
    else:
        output_json(p)


@app.command("delete")
def delete_prompt(
    slug: Annotated[str, typer.Argument(help="Prompt slug")],
) -> None:
    _api("DELETE", f"/{slug}")
    if is_compact():
        print(f"DELETED:{slug}")
    else:
        output_json({"deleted": slug})


@app.command("assign")
def assign_prompt(
    agent: Annotated[str, typer.Argument(help="Agent slug")],
    prompt: Annotated[str, typer.Argument(help="Prompt slug")],
    role: Annotated[str, typer.Argument(help="Role (system, guardrail, etc.)")],
    priority: Annotated[int, typer.Option("-p", "--priority", help="Priority (lower = first)")] = 0,
) -> None:
    payload = {"prompt_slug": prompt, "role": role, "priority": priority}
    _api("POST", f"/agents/{agent}/assignments", json=payload)
    if is_compact():
        print(f"ASSIGNED:{agent}<-{prompt}|{role}|{priority}")
    else:
        output_json({"assigned": prompt, "agent": agent, "role": role, "priority": priority})


@app.command("unassign")
def unassign_prompt(
    agent: Annotated[str, typer.Argument(help="Agent slug")],
    prompt: Annotated[str, typer.Argument(help="Prompt slug")],
) -> None:
    _api("DELETE", f"/agents/{agent}/assignments/{prompt}")
    if is_compact():
        print(f"UNASSIGNED:{agent}<-{prompt}")
    else:
        output_json({"unassigned": prompt, "agent": agent})


@app.command("assignments")
def list_assignments(
    agent: Annotated[str, typer.Argument(help="Agent slug")],
) -> None:
    data = _api("GET", f"/agents/{agent}/assignments")
    assignments = data.get("assignments", [])
    if is_compact():
        print(f"ASSIGN:{agent}[{len(assignments)}]")
        for a in assignments:
            p = a.get("prompt", {})
            print(f"  {p.get('slug', '?'):<20s} {a.get('role', '?'):<12s} {a.get('priority', 0)}")
    else:
        output_json(data)


@app.command("export")
def export_prompts(
    slug: Annotated[str | None, typer.Argument(help="Prompt slug (omit for all)")] = None,
    output_file: Annotated[Path | None, typer.Option("-o", "--output", help="Output file")] = None,
) -> None:
    """Export prompt(s) to YAML. Use for editing, then re-import."""
    if slug:
        p = _api("GET", f"/{slug}")
        entries = [p]
    else:
        data = _api("GET", "")
        entries = data.get("prompts", [])

    export_data = []
    for p in entries:
        entry: dict[str, Any] = {
            "slug": p["slug"],
            "name": p["name"],
            "is_global": p.get("is_global", False),
        }
        if p.get("description"):
            entry["description"] = p["description"]
        entry["content"] = p.get("content", "")
        export_data.append(entry)

    yaml_str = yaml.dump(export_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

    if output_file:
        output_file.write_text(yaml_str)
        if is_compact():
            print(f"EXPORTED[{len(export_data)}]:{output_file}")
        else:
            output_json({"exported": len(export_data), "file": str(output_file)})
    else:
        print(yaml_str)


@app.command("import")
def import_prompts(
    file: Annotated[Path, typer.Argument(help="YAML file to import")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without changes")] = False,
) -> None:
    """Import prompts from YAML. Creates if missing, updates if changed."""
    if not file.exists():
        output_error(f"File not found: {file}")
        raise typer.Exit(1)

    entries = yaml.safe_load(file.read_text())
    if not isinstance(entries, list):
        output_error("YAML must be a list of prompt objects")
        raise typer.Exit(1)

    existing_data = _api("GET", "")
    existing = {p["slug"]: p for p in existing_data.get("prompts", [])}

    created = updated = skipped = 0

    for entry in entries:
        slug = entry.get("slug")
        if not slug:
            output_error("Entry missing 'slug' — skipping")
            continue

        content = entry.get("content", "")
        name = entry.get("name", slug)
        is_global = entry.get("is_global", False)

        ex = existing.get(slug)

        if ex and ex.get("content", "").strip() == content.strip():
            skipped += 1
            continue

        if dry_run:
            action = "update" if ex else "create"
            lines = _line_count(content)
            print(f"  [{action}] {slug} ({lines}L)")
            if ex:
                updated += 1
            else:
                created += 1
            continue

        if ex:
            payload: dict[str, Any] = {"content": content, "name": name, "is_global": is_global}
            if entry.get("description"):
                payload["description"] = entry["description"]
            _api("PUT", f"/{slug}", json=payload)
            updated += 1
        else:
            payload = {"slug": slug, "name": name, "content": content, "is_global": is_global}
            if entry.get("description"):
                payload["description"] = entry["description"]
            _api("POST", "", json=payload)
            created += 1

    total = created + updated + skipped
    if is_compact():
        print(f"IMPORT[{total}]:created={created}|updated={updated}|skip={skipped}")
    else:
        output_json({"total": total, "created": created, "updated": updated, "skipped": skipped})

    assignments = [a for entry in entries for a in entry.get("assignments", [])]
    if not assignments or dry_run:
        return

    assign_created = assign_skipped = 0
    for assignment in assignments:
        agent_slug = assignment.get("agent")
        prompt_slug = assignment.get("prompt")
        role = assignment.get("role", "system")
        priority = assignment.get("priority", 0)

        if not agent_slug or not prompt_slug:
            continue

        try:
            agent_data = _api("GET", f"/agents/{agent_slug}/assignments")
        except SystemExit:
            assign_skipped += 1
            continue

        already = any(
            a.get("prompt", {}).get("slug") == prompt_slug for a in agent_data.get("assignments", [])
        )
        if already:
            assign_skipped += 1
            continue

        try:
            _api(
                "POST",
                f"/agents/{agent_slug}/assignments",
                json={"prompt_slug": prompt_slug, "role": role, "priority": priority},
            )
            assign_created += 1
        except SystemExit:
            assign_skipped += 1

    assign_total = assign_created + assign_skipped
    if is_compact():
        print(f"ASSIGN[{assign_total}]:created={assign_created}|skip={assign_skipped}")
    else:
        output_json({"assignments": {"total": assign_total, "created": assign_created, "skipped": assign_skipped}})
