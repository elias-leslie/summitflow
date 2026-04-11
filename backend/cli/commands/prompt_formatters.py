"""Output formatting for prompt management."""

from __future__ import annotations

from typing import Any

from ..output import is_compact, output_json


def line_count(content: str) -> int:
    """Count lines in content string."""
    return content.count("\n") + (1 if content and not content.endswith("\n") else 0)


def print_prompt_row(p: dict[str, Any]) -> None:
    """Print compact single-line prompt info."""
    slug = p["slug"]
    name = p["name"]
    g = "Y" if p.get("is_global") else "N"
    lines = line_count(p.get("content", ""))
    print(f"  {slug:<20s} {name:<24s} {g}   {lines}L")


def format_prompt_list(prompts: list[dict[str, Any]]) -> None:
    """Format and print prompt list."""
    if is_compact():
        print(f"PROMPTS[{len(prompts)}]")
        for p in prompts:
            print_prompt_row(p)
    else:
        output_json({"prompts": prompts})


def format_prompt_detail(p: dict[str, Any]) -> None:
    """Format and print single prompt detail."""
    if is_compact():
        g = "Y" if p.get("is_global") else "N"
        lines = line_count(p.get("content", ""))
        print(f"PROMPT:{p['slug']}|{p['name']}|{g}|{lines}L")
        print(p.get("content", ""))
    else:
        output_json(p)


def format_created(slug: str, content: str, prompt_data: dict[str, Any]) -> None:
    """Format and print created prompt confirmation."""
    if is_compact():
        lines = line_count(content)
        print(f"CREATED:{slug}|{lines}L")
    else:
        output_json(prompt_data)


def format_updated(slug: str, content: str, prompt_data: dict[str, Any]) -> None:
    """Format and print updated prompt confirmation."""
    if is_compact():
        lines = line_count(content)
        print(f"UPDATED:{slug}|{lines}L")
    else:
        output_json(prompt_data)


def format_deleted(slug: str) -> None:
    """Format and print deleted prompt confirmation."""
    if is_compact():
        print(f"DELETED:{slug}")
    else:
        output_json({"deleted": slug})


def format_assigned(agent: str, prompt: str, role: str, priority: int) -> None:
    """Format and print assignment confirmation."""
    if is_compact():
        print(f"ASSIGNED:{agent}<-{prompt}|{role}|{priority}")
    else:
        output_json({"assigned": prompt, "agent": agent, "role": role, "priority": priority})


def format_unassigned(agent: str, prompt: str) -> None:
    """Format and print unassignment confirmation."""
    if is_compact():
        print(f"UNASSIGNED:{agent}<-{prompt}")
    else:
        output_json({"unassigned": prompt, "agent": agent})


def format_assignments(agent: str, assignments: list[dict[str, Any]]) -> None:
    """Format and print agent assignments."""
    if is_compact():
        print(f"ASSIGN:{agent}[{len(assignments)}]")
        for a in assignments:
            p = a.get("prompt", {})
            print(f"  {p.get('slug', '?'):<20s} {a.get('role', '?'):<12s} {a.get('priority', 0)}")
    else:
        output_json({"assignments": assignments})


def format_prompt_revisions(slug: str, result: dict[str, Any]) -> None:
    """Format and print prompt revision history."""
    if is_compact():
        revisions = result.get("revisions", [])
        print(f"PROMPT_REVISIONS[{len(revisions)}]:slug={slug}")
        for revision in revisions:
            revision_id = str(revision.get("id", "?"))[:8]
            action = revision.get("action", "?")
            created_at = revision.get("created_at", "?")
            changed_by = revision.get("changed_by") or "-"
            change_reason = revision.get("change_reason") or "-"
            print(f"  {revision_id} [{action}] at={created_at} by={changed_by}")
            print(f"    reason={change_reason}")
    else:
        output_json(result)


def format_prompt_restored(slug: str, revision_id: str, prompt_data: dict[str, Any]) -> None:
    """Format and print prompt restore confirmation."""
    if is_compact():
        lines = line_count(prompt_data.get("content", ""))
        updated_at = prompt_data.get("updated_at", "?")
        print(f"PROMPT_RESTORED:{slug}:rev={revision_id[:8]}|{lines}L|updated_at={updated_at}")
    else:
        output_json(prompt_data)
