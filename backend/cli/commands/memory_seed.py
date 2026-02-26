"""Seed memory episodes from skill markdown files.

Reads .md files with YAML frontmatter from a skills/ directory and
upserts them as memory episodes. Uses `skill:<filename>` tag for
idempotent re-seeding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import typer

from ..output import output_error
from .memory_api import agent_hub_request

_HUB_TOOL = "st memory seed"

def _parse_fm_value(val: str) -> Any:
    """Parse a single YAML frontmatter value string into a Python type."""
    if val.startswith("[") and val.endswith("]"):
        return [i for i in (s.strip().strip("'\"") for s in val[1:-1].split(",")) if i]
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    if val.isdigit():
        return int(val)
    return val.strip("'\"")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown text. Returns (frontmatter, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm: dict[str, Any] = {}
    for raw in parts[1].strip().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        fm[key.strip()] = _parse_fm_value(val.strip())
    return fm, parts[2].strip()


def _build_skill_tag(filename: str) -> str:
    """Build a skill tag from filename for idempotent upserts."""
    return f"skill:{Path(filename).stem}"


def _find_existing_by_tag(skill_tag: str, scope: str, scope_id: str | None) -> dict[str, Any] | None:
    """Search for an existing episode with the given skill tag."""
    try:
        result = agent_hub_request(
            "GET", "/api/memory/search", params={"query": skill_tag, "limit": 5},
            scope=scope, scope_id=scope_id, tool_name=_HUB_TOOL,
        )
        for ep in result.get("results", []):
            if skill_tag in ep.get("tags", []):
                return cast(dict[str, Any], ep)
    except Exception:
        pass
    return None


def _build_episode_payload(skill_tag: str, content: str, fm: dict[str, Any]) -> dict[str, Any]:
    """Build the API payload for saving an episode."""
    tags = list(fm.get("tags", []))
    if skill_tag not in tags:
        tags.append(skill_tag)
    payload: dict[str, Any] = {
        "content": content, "injection_tier": fm.get("tier", "reference"),
        "confidence": 90, "summary": fm.get("summary", skill_tag), "tags": tags,
    }
    if fm.get("trigger_task_types"):
        payload["trigger_task_types"] = fm["trigger_task_types"]
    if fm.get("pinned"):
        payload["pinned"] = True
    return payload


def _upsert_skill_episode(
    skill_tag: str, content: str, frontmatter: dict[str, Any],
    scope: str, scope_id: str | None, dry_run: bool,
) -> str:
    """Upsert a skill episode. Returns action: 'created', 'updated', or 'unchanged'."""
    existing = _find_existing_by_tag(skill_tag, scope, scope_id)
    if existing:
        if existing.get("content", "").strip() == content.strip():
            return "unchanged"
        if dry_run:
            return "would_update"
        agent_hub_request(
            "DELETE", f"/api/memory/{existing['uuid']}",
            scope=scope, scope_id=scope_id, tool_name=_HUB_TOOL,
        )
    elif dry_run:
        return "would_create"
    agent_hub_request(
        "POST", "/api/memory/save",
        json=_build_episode_payload(skill_tag, content, frontmatter),
        scope=scope, scope_id=scope_id, tool_name=_HUB_TOOL,
    )
    return "updated" if existing else "created"


def _process_md_file(
    md_file: Path, scope: str, scope_id: str | None, dry_run: bool, results: dict[str, int],
) -> None:
    """Process one markdown file and update results counters in place."""
    skill_tag = _build_skill_tag(md_file.name)
    try:
        frontmatter, body = _parse_frontmatter(md_file.read_text())
        if not body.strip():
            typer.echo(f"  SKIP {md_file.name}: empty body")
            return
        action = _upsert_skill_episode(skill_tag, body, frontmatter, scope, scope_id, dry_run)
        typer.echo(f"  {action.replace('would_', '').upper()} {md_file.name} [{skill_tag}]")
        key = action.replace("would_", "")
        results[key] = results.get(key, 0) + 1
    except Exception as e:
        typer.echo(f"  FAILED {md_file.name}: {e}")
        results["failed"] += 1


def seed_impl(
    directory: Path, scope: str, scope_id: str | None, dry_run: bool, project: str | None,
) -> None:
    """Seed memory episodes from markdown files in a directory."""
    if not directory.exists():
        output_error(f"Directory not found: {directory}")
        raise typer.Exit(1)
    if not directory.is_dir():
        output_error(f"Not a directory: {directory}")
        raise typer.Exit(1)
    if project:
        scope, scope_id = "project", project
    md_files = sorted(directory.glob("*.md"))
    if not md_files:
        typer.echo(f"No .md files found in {directory}")
        return
    typer.echo(f"{'DRY RUN: Processing' if dry_run else 'Seeding'} {len(md_files)} files from {directory}")
    results: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for md_file in md_files:
        _process_md_file(md_file, scope, scope_id, dry_run, results)
    typer.echo(
        f"\nSeed complete: {results['created']} created, {results['updated']} updated, "
        f"{results['unchanged']} unchanged, {results['failed']} failed"
    )
