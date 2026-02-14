"""Seed memory episodes from skill markdown files.

Reads .md files with YAML frontmatter from a skills/ directory and
upserts them as memory episodes. Uses `skill:<filename>` tag for
idempotent re-seeding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from ..output import output_error
from .memory_api import agent_hub_request


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown text.

    Returns:
        Tuple of (frontmatter dict, body text)
    """
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    # Parse simple YAML key-value pairs (avoid heavy yaml dependency)
    frontmatter: dict[str, Any] = {}
    for line in parts[1].strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        # Parse lists: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip().strip("'\"") for item in value[1:-1].split(",")]
            frontmatter[key] = [i for i in items if i]
        # Parse booleans
        elif value.lower() in ("true", "yes"):
            frontmatter[key] = True
        elif value.lower() in ("false", "no"):
            frontmatter[key] = False
        # Parse numbers
        elif value.isdigit():
            frontmatter[key] = int(value)
        else:
            frontmatter[key] = value.strip("'\"")

    body = parts[2].strip()
    return frontmatter, body


def _build_skill_tag(filename: str) -> str:
    """Build a skill tag from filename for idempotent upserts."""
    stem = Path(filename).stem
    return f"skill:{stem}"


def _find_existing_by_tag(
    skill_tag: str,
    scope: str,
    scope_id: str | None,
) -> dict[str, Any] | None:
    """Search for an existing episode with the given skill tag."""
    try:
        result = agent_hub_request(
            "GET",
            "/api/memory/search",
            params={"query": skill_tag, "limit": 5},
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory seed",
        )
        for ep in result.get("results", []):
            tags = ep.get("tags", [])
            if skill_tag in tags:
                return ep
    except Exception:
        pass
    return None


def _upsert_skill_episode(
    skill_tag: str,
    content: str,
    frontmatter: dict[str, Any],
    scope: str,
    scope_id: str | None,
    dry_run: bool,
) -> str:
    """Upsert a skill episode. Returns action taken: 'created', 'updated', or 'unchanged'."""
    tier = frontmatter.get("tier", "reference")
    summary = frontmatter.get("summary", skill_tag)
    trigger_types = frontmatter.get("trigger_task_types", [])
    pinned = frontmatter.get("pinned", False)
    tags = frontmatter.get("tags", [])
    if skill_tag not in tags:
        tags.append(skill_tag)

    existing = _find_existing_by_tag(skill_tag, scope, scope_id)

    if existing:
        existing_content = existing.get("content", "")
        if existing_content.strip() == content.strip():
            return "unchanged"

        if dry_run:
            return "would_update"

        # Delete and recreate (content change requires delete+create)
        uuid = existing["uuid"]
        agent_hub_request(
            "DELETE",
            f"/api/memory/{uuid}",
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory seed",
        )

    if dry_run:
        return "would_create" if not existing else "would_update"

    payload: dict[str, Any] = {
        "content": content,
        "injection_tier": tier,
        "confidence": 90,
        "summary": summary,
        "tags": tags,
    }
    if trigger_types:
        payload["trigger_task_types"] = trigger_types
    if pinned:
        payload["pinned"] = True

    agent_hub_request(
        "POST",
        "/api/memory/save",
        json=payload,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory seed",
    )
    return "updated" if existing else "created"


def seed_impl(
    directory: Path,
    scope: str,
    scope_id: str | None,
    dry_run: bool,
    project: str | None,
) -> None:
    """Seed memory episodes from markdown files in a directory.

    Each .md file with YAML frontmatter becomes a memory episode.
    Uses skill:<filename> tag for idempotent re-seeding.

    Args:
        directory: Path to skills directory
        scope: Memory scope (global or project)
        scope_id: Scope ID for project-scoped episodes
        dry_run: Preview without writing
        project: Project name to use as scope_id
    """
    if not directory.exists():
        output_error(f"Directory not found: {directory}")
        raise typer.Exit(1)

    if not directory.is_dir():
        output_error(f"Not a directory: {directory}")
        raise typer.Exit(1)

    # Resolve scope from project name if provided
    if project:
        scope = "project"
        scope_id = project

    md_files = sorted(directory.glob("*.md"))
    if not md_files:
        typer.echo(f"No .md files found in {directory}")
        return

    if dry_run:
        typer.echo(f"DRY RUN: Processing {len(md_files)} files from {directory}")
    else:
        typer.echo(f"Seeding {len(md_files)} skill files from {directory}")

    results: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}

    for md_file in md_files:
        skill_tag = _build_skill_tag(md_file.name)
        try:
            text = md_file.read_text()
            frontmatter, body = _parse_frontmatter(text)

            if not body.strip():
                typer.echo(f"  SKIP {md_file.name}: empty body")
                continue

            action = _upsert_skill_episode(
                skill_tag, body, frontmatter, scope, scope_id, dry_run
            )

            display_action = action.replace("would_", "").upper()
            typer.echo(f"  {display_action} {md_file.name} [{skill_tag}]")

            if action.startswith("would_"):
                action = action.replace("would_", "")
            results[action] = results.get(action, 0) + 1

        except Exception as e:
            typer.echo(f"  FAILED {md_file.name}: {e}")
            results["failed"] += 1

    typer.echo(
        f"\nSeed complete: {results['created']} created, {results['updated']} updated, "
        f"{results['unchanged']} unchanged, {results['failed']} failed"
    )
