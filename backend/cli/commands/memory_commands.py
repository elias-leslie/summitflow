"""Command implementations for memory system."""

from __future__ import annotations

import datetime
import json as json_lib
import re
from pathlib import Path
from typing import Any

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext
from .memory_api import agent_hub_request
from .memory_formatters import (
    format_batch_get_compact,
    format_batch_tier_compact,
    format_get_compact,
    format_list_compact,
    format_orphaned_cleanup_compact,
    format_save_compact,
    format_search_compact,
    format_stale_cleanup_compact,
    format_stats_compact,
)

# FORMAT_STANDARD validation patterns
HEADER_PATTERN = re.compile(r"^\*\*[^*]+\*\*:")
CUSTOM_DELIMITER_PATTERN = re.compile(r"(?<![\|])\s*::\s*|(?<!\|)\s*->\s*(?!\|)")
CONVERSATIONAL_PATTERNS = [
    "please",
    "thank you",
    "you should",
    "i recommend",
    "remember",
    "make sure",
    "note:",
    "important:",
    "consider using",
    "feel free",
    "you might want",
    "it would be",
    "it's important to",
    "let me know",
    "i suggest",
]

FORMAT_STANDARD_HELP = """
FORMAT_STANDARD for memory episodes:

| # | Rule | Check |
|---|------|-------|
| 1 | Header format | Must start with **Topic**: |
| 2 | Imperative mood | Commands not suggestions |
| 3 | Articles dropped | Remove the/a/an where natural |
| 4 | One atomic rule | Single concept per episode |
| 5 | No custom delimiters | No ::, -> except in tables |
| 6 | No conversational | No please/remember/note:/you should |
| 7 | Terse content | Compress wordiness |
| 8 | Summary | 10-40 chars |

Example of GOOD format:
  **Git Safety**: Never git stash. Use /commit_it first. Lost work risk.

Example of BAD format:
  When working with git, you should remember to always commit first.
  Please don't use git stash because it might cause lost work.
"""


def validate_format_standard(content: str, summary: str) -> list[str]:
    """Validate content against FORMAT_STANDARD. Returns list of errors."""
    errors: list[str] = []

    # Rule 1: Header format - must start with **Topic**:
    if not HEADER_PATTERN.match(content):
        errors.append("[1] header: Must start with **Topic**: format")

    # Rule 5: No custom delimiters (:: or -> outside tables)
    # Allow | for tables, but catch standalone :: and ->
    lines = content.split("\n")
    for i, line in enumerate(lines):
        # Skip table rows (contain |)
        if "|" in line:
            continue
        if "::" in line or re.search(r"(?<!\|)\s*->\s*(?!\|)", line):
            errors.append(f"[5] delimiters: Line {i + 1} has :: or -> (use tables or rewrite)")
            break

    # Rule 6: No conversational patterns
    content_lower = content.lower()
    found_patterns = [p for p in CONVERSATIONAL_PATTERNS if p in content_lower]
    if found_patterns:
        errors.append(f"[6] conversational: Remove patterns: {', '.join(found_patterns[:3])}")

    # Rule 8: Summary length (10-40 chars)
    if len(summary) < 10:
        errors.append(f"[8] summary: Too short ({len(summary)} chars, need 10-40)")

    return errors


def stats_impl(out: OutputContext, scope: str, scope_id: str | None) -> None:
    result = agent_hub_request(
        "GET",
        "/api/memory/stats",
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory stats",
    )

    if out.is_compact:
        format_stats_compact(result)
    else:
        output_json(result)


def save_impl(
    out: OutputContext,
    content: str,
    summary: str,
    tier: str,
    confidence: int,
    context: str | None,
    pinned: bool,
    trigger_types: str | None,
    scope: str,
    scope_id: str | None,
) -> None:
    if tier not in ("mandate", "guardrail", "reference"):
        output_error(f"Invalid tier: {tier}. Must be mandate, guardrail, or reference.")
        raise typer.Exit(1)

    if confidence < 0 or confidence > 100:
        output_error(f"Invalid confidence: {confidence}. Must be 0-100.")
        raise typer.Exit(1)

    if not summary or not summary.strip():
        output_error("--summary is required. Provide a short action phrase (~35 chars).")
        raise typer.Exit(1)

    summary = summary.strip()
    if len(summary) > 40:
        output_error(f"Summary too long ({len(summary)} chars). Keep it under 40 chars.")
        raise typer.Exit(1)

    # FORMAT_STANDARD validation
    format_errors = validate_format_standard(content, summary)
    if format_errors:
        output_error("FORMAT_STANDARD violations detected:")
        for err in format_errors:
            typer.echo(f"  {err}", err=True)
        typer.echo(FORMAT_STANDARD_HELP, err=True)
        raise typer.Exit(1)

    if content.count(".") > 3 or len(content) > 500:
        typer.echo("Hint: Long content detected. Is this ONE rule or multiple?")
        typer.echo("      Multiple rules = split into separate episodes for clarity.")

    payload: dict[str, Any] = {
        "content": content,
        "injection_tier": tier,
        "confidence": confidence,
        "summary": summary,
    }
    if context:
        payload["context"] = context
    if pinned:
        payload["pinned"] = True
    if trigger_types:
        payload["trigger_task_types"] = [t.strip() for t in trigger_types.split(",")]

    result = agent_hub_request(
        "POST",
        "/api/memory/save-learning",
        json=payload,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory save",
    )

    if out.is_compact:
        format_save_compact(result)
    else:
        output_json(result)


def list_impl(
    out: OutputContext,
    limit: int,
    cursor: str | None,
    tier: str | None,
    scope: str,
    scope_id: str | None,
) -> None:
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if tier:
        params["category"] = tier

    result = agent_hub_request(
        "GET",
        "/api/memory/list",
        params=params,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory list",
    )

    if out.is_compact:
        format_list_compact(result)
    else:
        output_json(result)


def search_impl(
    out: OutputContext,
    query: str,
    limit: int,
    min_score: float,
    scope: str,
    scope_id: str | None,
) -> None:
    params: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "min_score": min_score,
    }

    result = agent_hub_request(
        "GET",
        "/api/memory/search",
        params=params,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory search",
    )

    if out.is_compact:
        format_search_compact(result)
    else:
        output_json(result)


def get_impl(out: OutputContext, uuids: list[str]) -> None:
    if not uuids:
        output_error("At least one UUID required")
        raise typer.Exit(1)

    if len(uuids) == 1:
        result = agent_hub_request(
            "GET",
            f"/api/memory/episode/{uuids[0]}",
            tool_name="st memory get",
        )

        if "detail" in result:
            output_error(result["detail"])
            raise typer.Exit(1)

        if out.is_compact:
            format_get_compact(result)
        else:
            output_json(result)
    else:
        result = agent_hub_request(
            "POST",
            "/api/memory/batch-get",
            json={"uuids": uuids},
            tool_name="st memory get",
        )

        if out.is_compact:
            format_batch_get_compact(result)
        else:
            output_json(result)


def delete_impl(uuids: list[str], confirm: bool) -> None:
    if confirm:
        typer.echo(f"Will delete {len(uuids)} episode(s):")
        for uuid in uuids:
            typer.echo(f"  - {uuid[:8]}...")

        if not typer.confirm("Proceed with deletion?"):
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    if len(uuids) == 1:
        result = agent_hub_request(
            "DELETE",
            f"/api/memory/episode/{uuids[0]}",
            tool_name="st memory delete",
        )
        if result.get("success"):
            typer.echo(f"Deleted: {uuids[0][:8]}")
            typer.echo("\nDeleted: 1, Failed: 0")
        else:
            typer.echo(f"Failed: {uuids[0][:8]} - {result.get('detail', 'Unknown error')}")
            typer.echo("\nDeleted: 0, Failed: 1")
    else:
        result = agent_hub_request(
            "POST",
            "/api/memory/bulk-delete",
            json={"ids": uuids},
            tool_name="st memory delete",
        )
        deleted = result.get("deleted", 0)
        failed = result.get("failed", 0)
        for error in result.get("errors", []):
            typer.echo(f"Failed: {error['id'][:8]} - {error.get('error', 'Unknown')}")
        typer.echo(f"\nDeleted: {deleted}, Failed: {failed}")


def update_impl(
    uuid: str,
    content: str | None,
    tier: str | None,
    summary: str | None,
    trigger_types: str | None,
    pinned: bool | None,
    confirm: bool,
) -> None:
    if not any([content, tier, summary, trigger_types, pinned is not None]):
        typer.echo(
            "Error: Must specify at least one of: --content, --tier, --summary, --trigger-types, --pinned"
        )
        raise typer.Exit(1)

    if summary and len(summary) > 40:
        typer.echo(f"Error: Summary too long ({len(summary)} chars). Keep it under 40 chars.")
        raise typer.Exit(1)

    existing = agent_hub_request("GET", f"/api/memory/episode/{uuid}", tool_name="st memory update")
    if "detail" in existing:
        typer.echo(f"Error: {existing['detail']}")
        raise typer.Exit(1)

    full_uuid = existing.get("uuid", uuid)
    old_tier = existing.get("injection_tier", "reference")
    old_content = existing.get("content", "")

    content_or_tier_changed = bool(content or tier)
    properties_changed = bool(summary or trigger_types or pinned is not None)

    # FORMAT_STANDARD validation for content updates
    if content:
        effective_summary = summary or existing.get("summary", "")
        format_errors = validate_format_standard(content, effective_summary)
        if format_errors:
            output_error("FORMAT_STANDARD violations detected:")
            for err in format_errors:
                typer.echo(f"  {err}", err=True)
            typer.echo(FORMAT_STANDARD_HELP, err=True)
            raise typer.Exit(1)

        if content.count(".") > 3 or len(content) > 500:
            typer.echo("Hint: Long content detected. Is this ONE rule or multiple?")
            typer.echo("      Multiple rules = split into separate episodes for clarity.")

    if confirm:
        typer.echo(f"  UUID: {uuid[:8]}...")
        if tier:
            typer.echo(f"  Tier: {old_tier} -> {tier}")
        if content:
            typer.echo(f"  Old content: {old_content}")
            typer.echo(f"  New content: {content}")
        if summary:
            typer.echo(f"  Summary: {summary}")
        if trigger_types:
            typer.echo(f"  Trigger types: {trigger_types}")
        if pinned is not None:
            typer.echo(f"  Pinned: {pinned}")
        if content_or_tier_changed:
            typer.echo("  Usage stats will be preserved.")

        if not typer.confirm("Proceed with update?"):
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    target_uuid = full_uuid

    if content_or_tier_changed:
        new_content = content if content else old_content
        new_tier = tier if tier else old_tier

        create_result = agent_hub_request(
            "POST",
            "/api/memory/add",
            json={
                "content": new_content,
                "name": existing.get("name", "updated_episode"),
                "injection_tier": new_tier,
                "preserve_stats_from": full_uuid,
            },
            tool_name="st memory update",
        )

        new_uuid = create_result.get("uuid")
        if not new_uuid:
            typer.echo(f"Error creating new episode: {create_result}")
            raise typer.Exit(1)

        delete_result = agent_hub_request(
            "DELETE", f"/api/memory/episode/{uuid}", tool_name="st memory update"
        )
        if not delete_result.get("success"):
            typer.echo(
                f"Warning: Failed to delete original: {delete_result.get('detail', 'Unknown')}"
            )
            typer.echo(f"New episode created: {new_uuid[:8]}")
            typer.echo(f"Please manually delete: {uuid[:8]}")
            raise typer.Exit(1)

        target_uuid = new_uuid
        typer.echo(f"Updated: {uuid[:8]} -> {new_uuid[:8]}")
        if tier:
            typer.echo(f"  Tier: {new_tier}")

    if properties_changed:
        props: dict[str, Any] = {}
        if summary:
            props["summary"] = summary
        if trigger_types:
            props["trigger_task_types"] = [t.strip() for t in trigger_types.split(",")]
        if pinned is not None:
            props["pinned"] = pinned

        patch_result = agent_hub_request(
            "PATCH",
            f"/api/memory/episode/{target_uuid}/properties",
            json=props,
            tool_name="st memory update",
        )

        if not patch_result.get("success"):
            typer.echo(
                f"Warning: Failed to update properties: {patch_result.get('message', 'Unknown')}"
            )
        else:
            if summary:
                typer.echo(f"  Summary: {summary}")
            if trigger_types:
                typer.echo(f"  Trigger types: {props['trigger_task_types']}")
            if pinned is not None:
                typer.echo(f"  Pinned: {pinned}")

    if not content_or_tier_changed and not properties_changed:
        typer.echo("No changes made.")


def batch_tier_impl(
    out: OutputContext,
    input_file: Path | None,
    json_input: str | None,
    tier: str | None,
    uuids: list[str] | None,
) -> None:
    updates: list[dict[str, str]] = []

    if input_file:
        if not input_file.exists():
            typer.echo(f"Error: File not found: {input_file}")
            raise typer.Exit(1)
        raw_updates = json_lib.loads(input_file.read_text())
        updates = [
            {"uuid": u["uuid"], "injection_tier": u.get("tier", u.get("injection_tier"))}
            for u in raw_updates
        ]
    elif json_input:
        raw_updates = json_lib.loads(json_input)
        updates = [
            {"uuid": u["uuid"], "injection_tier": u.get("tier", u.get("injection_tier"))}
            for u in raw_updates
        ]
    elif tier and uuids:
        updates = [{"uuid": u, "injection_tier": tier} for u in uuids]
    else:
        typer.echo("Error: Provide --file, --json, or (UUIDs with --tier)")
        raise typer.Exit(1)

    if not updates:
        typer.echo("Error: No updates provided")
        raise typer.Exit(1)

    result = agent_hub_request(
        "POST",
        "/api/memory/batch-update",
        json={"updates": updates},
        tool_name="st memory batch-tier",
    )

    if out.is_compact:
        format_batch_tier_compact(result)
    else:
        typer.echo(f"Updated: {result['updated']}/{result['total']}")
        if result.get("failed", 0) > 0:
            typer.echo("Failed updates:")
            for r in result.get("results", []):
                if not r.get("success"):
                    typer.echo(f"  {r['uuid'][:8]}: {r.get('error', 'Unknown')}")


MINIMAL_EXPORT_FIELDS = [
    "uuid",
    "name",
    "content",
    "category",
    "summary",
    "scope",
    "scope_id",
    "pinned",
]
SPLIT_THRESHOLD = 25


def _filter_episode_fields(episode: dict[str, Any], full: bool) -> dict[str, Any]:
    """Filter episode to minimal fields unless full export requested."""
    if full:
        return episode
    return {k: v for k, v in episode.items() if k in MINIMAL_EXPORT_FIELDS}


def _write_export_file(path: Path, episodes: list[dict[str, Any]], full: bool) -> None:
    """Write episodes to a JSON file with metadata."""
    from datetime import UTC

    filtered = [_filter_episode_fields(ep, full) for ep in episodes]
    export_data = {
        "exported_at": datetime.datetime.now(UTC).isoformat(),
        "count": len(filtered),
        "episodes": filtered,
    }
    path.write_text(json_lib.dumps(export_data, indent=2, default=str))


def export_impl(
    tier: str | None,
    uuids: list[str] | None,
    output: Path | None,
    scope: str,
    scope_id: str | None,
    full: bool = False,
) -> None:
    episodes: list[dict[str, Any]] = []

    if uuids:
        result = agent_hub_request(
            "POST",
            "/api/memory/batch-get",
            json={"uuids": uuids},
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory export",
        )
        episodes = list(result.get("episodes", {}).values())
    else:
        params: dict[str, Any] = {"limit": 100}
        if tier:
            params["category"] = tier

        result = agent_hub_request(
            "GET",
            "/api/memory/list",
            params=params,
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory export",
        )
        episodes = result.get("episodes", [])

        while result.get("has_more"):
            params["cursor"] = result.get("cursor")
            result = agent_hub_request(
                "GET",
                "/api/memory/list",
                params=params,
                scope=scope,
                scope_id=scope_id,
                tool_name="st memory export",
            )
            episodes.extend(result.get("episodes", []))

    if output and output.suffix == "":
        output.mkdir(parents=True, exist_ok=True)

        by_tier: dict[str, list[dict[str, Any]]] = {"mandate": [], "guardrail": [], "reference": []}
        for ep in episodes:
            ep_tier = ep.get("category") or ep.get("injection_tier", "reference")
            if ep_tier in by_tier:
                by_tier[ep_tier].append(ep)
            else:
                by_tier["reference"].append(ep)

        files_written = []
        for tier_name, tier_episodes in by_tier.items():
            if not tier_episodes:
                continue

            if len(tier_episodes) <= SPLIT_THRESHOLD:
                file_path = output / f"{tier_name}s.json"
                _write_export_file(file_path, tier_episodes, full)
                files_written.append(f"{tier_name}s.json ({len(tier_episodes)})")
            else:
                for i, chunk_start in enumerate(range(0, len(tier_episodes), SPLIT_THRESHOLD), 1):
                    chunk = tier_episodes[chunk_start : chunk_start + SPLIT_THRESHOLD]
                    file_path = output / f"{tier_name}s-{i}.json"
                    _write_export_file(file_path, chunk, full)
                    files_written.append(f"{tier_name}s-{i}.json ({len(chunk)})")

        typer.echo(f"Exported {len(episodes)} episodes to {output}/")
        for f in files_written:
            typer.echo(f"  {f}")
    else:
        filtered = [_filter_episode_fields(ep, full) for ep in episodes]
        export_data = {
            "exported_at": datetime.datetime.now().isoformat(),
            "count": len(filtered),
            "episodes": filtered,
        }

        json_output = json_lib.dumps(export_data, indent=2, default=str)

        if output:
            output.write_text(json_output)
            typer.echo(f"Exported {len(episodes)} episodes to {output}")
        else:
            typer.echo(json_output)


def import_impl(out: OutputContext, input_path: Path, dry_run: bool) -> None:
    if not input_path.exists():
        output_error(f"Path not found: {input_path}")
        raise typer.Exit(1)

    all_episodes: list[dict[str, Any]] = []

    if input_path.is_dir():
        json_files = sorted(input_path.glob("*.json"))
        if not json_files:
            output_error(f"No .json files found in {input_path}")
            raise typer.Exit(1)
        for json_file in json_files:
            data = json_lib.loads(json_file.read_text())
            all_episodes.extend(data.get("episodes", []))
        typer.echo(
            f"Loaded {len(all_episodes)} episodes from {len(json_files)} files in {input_path}/"
        )
    else:
        data = json_lib.loads(input_path.read_text())
        all_episodes = data.get("episodes", [])

    episodes = all_episodes

    if not episodes:
        typer.echo("No episodes to import")
        return

    imported_by_uuid = {ep["uuid"]: ep for ep in episodes if ep.get("uuid")}

    current_result = agent_hub_request(
        "GET",
        "/api/memory/list",
        params={"limit": 300},
        tool_name="st memory import",
    )
    current_episodes = current_result.get("episodes", [])
    current_by_uuid = {ep["uuid"]: ep for ep in current_episodes}

    content_changes: list[dict[str, Any]] = []
    property_updates: list[dict[str, Any]] = []

    for uuid, imported_ep in imported_by_uuid.items():
        current_ep = current_by_uuid.get(uuid)
        if not current_ep:
            continue

        imported_content = imported_ep.get("content", "")
        current_content = current_ep.get("content", "")

        if imported_content != current_content:
            content_changes.append(
                {
                    "uuid": uuid,
                    "old_content": current_content,
                    "new_content": imported_content,
                    "name": current_ep.get("name", "imported_episode"),
                    "tier": imported_ep.get("category")
                    or current_ep.get("injection_tier", "reference"),
                }
            )
            continue

        update: dict[str, Any] = {"uuid": uuid}
        if imported_ep.get("injection_tier"):
            update["injection_tier"] = imported_ep["injection_tier"]
        if imported_ep.get("summary") is not None:
            update["summary"] = imported_ep["summary"]
        if imported_ep.get("trigger_task_types") is not None:
            update["trigger_task_types"] = imported_ep["trigger_task_types"]
        if imported_ep.get("pinned") is not None:
            update["pinned"] = imported_ep["pinned"]
        if imported_ep.get("auto_inject") is not None:
            update["auto_inject"] = imported_ep["auto_inject"]
        if imported_ep.get("display_order") is not None:
            update["display_order"] = imported_ep["display_order"]

        if len(update) > 1:
            property_updates.append(update)

    if dry_run:
        typer.echo(
            f"DRY RUN: {len(content_changes)} content changes, {len(property_updates)} property updates"
        )
        if content_changes:
            typer.echo("Content changes (delete+recreate):")
            for c in content_changes:
                typer.echo(f"  {c['uuid'][:8]}: content changed")
        if property_updates:
            typer.echo("Property updates (batch):")
            for u in property_updates:
                fields = [k for k in u if k != "uuid"]
                typer.echo(f"  {u['uuid'][:8]}: {', '.join(fields)}")
        return

    if not content_changes and not property_updates:
        typer.echo("No updates needed")
        return

    content_success = 0
    content_failed = 0
    for change in content_changes:
        try:
            create_result = agent_hub_request(
                "POST",
                "/api/memory/add",
                json={
                    "content": change["new_content"],
                    "name": change["name"],
                    "injection_tier": change["tier"],
                    "preserve_stats_from": change["uuid"],
                },
                tool_name="st memory import",
            )
            new_uuid = create_result.get("uuid")
            if not new_uuid:
                typer.echo(f"  {change['uuid'][:8]}: failed to create - {create_result}")
                content_failed += 1
                continue

            delete_result = agent_hub_request(
                "DELETE",
                f"/api/memory/episode/{change['uuid']}",
                tool_name="st memory import",
            )
            if delete_result.get("success"):
                typer.echo(f"  {change['uuid'][:8]} -> {new_uuid[:8]}: content updated")
                content_success += 1
            else:
                typer.echo(
                    f"  {change['uuid'][:8]}: created {new_uuid[:8]} but failed to delete original"
                )
                content_failed += 1
        except Exception as e:
            typer.echo(f"  {change['uuid'][:8]}: error - {e}")
            content_failed += 1

    prop_updated = 0
    prop_failed = 0
    if property_updates:
        result = agent_hub_request(
            "POST",
            "/api/memory/batch-update",
            json={"updates": property_updates},
            tool_name="st memory import",
        )
        prop_updated = result.get("updated", 0)
        prop_failed = result.get("failed", 0)

    if out.is_compact:
        typer.echo(
            f"IMPORT:content={content_success}/{len(content_changes)}|props={prop_updated}/{len(property_updates)}"
        )
    else:
        typer.echo(f"Content updates: {content_success}/{len(content_changes)}")
        typer.echo(f"Property updates: {prop_updated}/{len(property_updates)}")
        if content_failed > 0 or prop_failed > 0:
            typer.echo(f"Failed: {content_failed + prop_failed}")


def cleanup_impl(
    out: OutputContext,
    orphaned: bool,
    stale: bool,
    ttl_days: int,
    scope: str,
    scope_id: str | None,
) -> None:
    if not orphaned and not stale:
        typer.echo("Error: Must specify --orphaned and/or --stale")
        raise typer.Exit(1)

    if orphaned:
        result = agent_hub_request(
            "POST",
            "/api/memory/cleanup-orphaned",
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory cleanup --orphaned",
        )
        if out.is_compact:
            format_orphaned_cleanup_compact(result)
        else:
            output_json(result)

    if stale:
        result = agent_hub_request(
            "POST",
            f"/api/memory/cleanup?ttl_days={ttl_days}",
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory cleanup --stale",
        )
        if out.is_compact:
            format_stale_cleanup_compact(result)
        else:
            output_json(result)
