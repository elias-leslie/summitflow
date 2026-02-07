"""Prompt management CLI — CRUD, assignments, seed, and sync."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from ..output import is_compact, output_error, output_json
from .memory_api import agent_hub_request

app = typer.Typer(help="Prompt management (Agent Hub)")

DEFAULT_PROMPTS_DIR = Path.home() / "agent-hub" / "backend" / "prompts"

SEED_MAP: dict[str, dict[str, Any]] = {
    "coder.md": {"slug": "coder", "name": "Coder Agent", "is_global": False, "assign": ("coder", "system", 0)},
    "planner.md": {"slug": "planner", "name": "Planner Agent", "is_global": False, "assign": ("planner", "system", 0)},
    "reviewer.md": {"slug": "reviewer", "name": "Reviewer Agent", "is_global": False, "assign": ("reviewer", "system", 0)},
    "refactor.md": {"slug": "refactor", "name": "Refactor Agent", "is_global": False, "assign": ("refactor", "system", 0)},
    "validator.md": {"slug": "validator", "name": "Validator Agent", "is_global": False, "assign": ("validator", "system", 0)},
    "explorer.md": {"slug": "explorer", "name": "Explorer Agent", "is_global": False, "assign": ("explorer", "system", 0)},
    "designer.md": {"slug": "designer", "name": "Designer Agent", "is_global": False, "assign": ("designer", "system", 0)},
    "qa.md": {"slug": "qa", "name": "QA Agent", "is_global": False, "assign": ("qa", "system", 0)},
    "qa_plan_defect.md": {"slug": "qa-plan-defect", "name": "QA Plan Defect", "is_global": False, "assign": ("qa", "plan-defect", 10)},
    "safety_directive.md": {"slug": "safety-directive", "name": "Safety Directive", "is_global": True, "assign": None},
}


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


@app.command("seed")
def seed_prompts(
    prompts_dir: Annotated[
        Path, typer.Option("--dir", help="Directory with .md prompt files"),
    ] = DEFAULT_PROMPTS_DIR,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without changes")] = False,
) -> None:
    if not prompts_dir.is_dir():
        output_error(f"Prompts directory not found: {prompts_dir}")
        raise typer.Exit(1)

    existing_data = _api("GET", "")
    existing = {p["slug"]: p for p in existing_data.get("prompts", [])}

    created = updated = skipped = 0

    for filename, meta in SEED_MAP.items():
        filepath = prompts_dir / filename
        if not filepath.exists():
            output_error(f"Missing: {filepath}")
            continue

        content = filepath.read_text()
        slug = meta["slug"]
        ex = existing.get(slug)

        if ex and ex.get("content", "").strip() == content.strip():
            skipped += 1
            continue

        if dry_run:
            action = "update" if ex else "create"
            lines = _line_count(content)
            print(f"  [dry-run] {action}: {slug} ({lines}L)")
            if ex:
                updated += 1
            else:
                created += 1
            continue

        if ex:
            _api("PUT", f"/{slug}", json={"content": content, "name": meta["name"], "is_global": meta["is_global"]})
            updated += 1
        else:
            _api("POST", "", json={"slug": slug, "name": meta["name"], "content": content, "is_global": meta["is_global"]})
            created += 1

    total = created + updated + skipped
    if is_compact():
        print(f"SEED[{total}]:created={created}|updated={updated}|skip={skipped}")
    else:
        output_json({"total": total, "created": created, "updated": updated, "skipped": skipped})

    if dry_run:
        return

    assign_created = assign_skipped = 0
    for _filename, meta in SEED_MAP.items():
        assign_info = meta.get("assign")
        if not assign_info:
            continue
        agent_slug, role, priority = assign_info
        try:
            agent_data = _api("GET", f"/agents/{agent_slug}/assignments")
        except SystemExit:
            output_error(f"Agent '{agent_slug}' not found — skipping assignment")
            assign_skipped += 1
            continue

        already = any(
            a.get("prompt", {}).get("slug") == meta["slug"] for a in agent_data.get("assignments", [])
        )
        if already:
            assign_skipped += 1
            continue

        try:
            _api("POST", f"/agents/{agent_slug}/assignments", json={"prompt_slug": meta["slug"], "role": role, "priority": priority})
            assign_created += 1
        except SystemExit:
            assign_skipped += 1

    assign_total = assign_created + assign_skipped
    if is_compact():
        print(f"ASSIGN[{assign_total}]:created={assign_created}|skip={assign_skipped}")
    else:
        output_json({"assignments": {"total": assign_total, "created": assign_created, "skipped": assign_skipped}})


@app.command("sync")
def sync_prompts(
    prompts_dir: Annotated[
        Path, typer.Option("--dir", help="Directory with .md prompt files"),
    ] = DEFAULT_PROMPTS_DIR,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without changes")] = False,
) -> None:
    if not prompts_dir.is_dir():
        output_error(f"Prompts directory not found: {prompts_dir}")
        raise typer.Exit(1)

    existing_data = _api("GET", "")
    existing = {p["slug"]: p for p in existing_data.get("prompts", [])}

    updated_count = unchanged = missing = 0

    for filename, meta in SEED_MAP.items():
        filepath = prompts_dir / filename
        slug = meta["slug"]

        if not filepath.exists():
            missing += 1
            if is_compact():
                print(f"  MISSING:{slug} ({filename})")
            continue

        content = filepath.read_text()
        ex = existing.get(slug)

        if not ex:
            missing += 1
            if is_compact():
                print(f"  NOT_IN_DB:{slug}")
            continue

        if ex.get("content", "").strip() == content.strip():
            unchanged += 1
            continue

        if dry_run:
            lines = _line_count(content)
            print(f"  [dry-run] update: {slug} ({lines}L)")
            updated_count += 1
            continue

        _api("PUT", f"/{slug}", json={"content": content})
        updated_count += 1

    total = updated_count + unchanged + missing
    if is_compact():
        print(f"SYNC[{total}]:updated={updated_count}|unchanged={unchanged}|missing={missing}")
    else:
        output_json({"total": total, "updated": updated_count, "unchanged": unchanged, "missing": missing})
