"""Batch operations for memory system."""

from __future__ import annotations

import datetime
import json as json_lib
from pathlib import Path
from typing import Any

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext
from .memory_api import agent_hub_request
from .memory_formatters import (
    format_batch_tier_compact,
    format_orphaned_cleanup_compact,
    format_stale_cleanup_compact,
)

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
