"""Command implementations for memory system."""

from __future__ import annotations

import datetime
import json as json_lib
from pathlib import Path
from typing import Any

import typer

from ..output import is_compact, output_error, output_json
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


def stats_impl(scope: str, scope_id: str | None) -> None:
    result = agent_hub_request(
        "GET",
        "/api/memory/stats",
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory stats",
    )

    if is_compact():
        format_stats_compact(result)
    else:
        output_json(result)


def save_impl(
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
        output_error("--summary is required. Provide a short action phrase (~20 chars).")
        raise typer.Exit(1)

    summary = summary.strip()
    if len(summary) > 30:
        output_error(f"Summary too long ({len(summary)} chars). Keep it under 30 chars.")
        raise typer.Exit(1)

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

    if is_compact():
        format_save_compact(result)
    else:
        output_json(result)


def list_impl(
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

    if is_compact():
        format_list_compact(result)
    else:
        output_json(result)


def search_impl(
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

    if is_compact():
        format_search_compact(result)
    else:
        output_json(result)


def get_impl(uuids: list[str]) -> None:
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

        if is_compact():
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

        if is_compact():
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

    deleted = 0
    failed = 0

    for uuid in uuids:
        result = agent_hub_request(
            "DELETE",
            f"/api/memory/episode/{uuid}",
            tool_name="st memory delete",
        )
        if result.get("success"):
            typer.echo(f"Deleted: {uuid[:8]}")
            deleted += 1
        else:
            typer.echo(f"Failed: {uuid[:8]} - {result.get('detail', 'Unknown error')}")
            failed += 1

    typer.echo(f"\nDeleted: {deleted}, Failed: {failed}")


def update_impl(
    uuid: str,
    content: str | None,
    tier: str | None,
    trigger_types: str | None,
    pinned: bool | None,
    confirm: bool,
) -> None:
    if not any([content, tier, trigger_types, pinned is not None]):
        typer.echo(
            "Error: Must specify at least one of: --content, --tier, --trigger-types, --pinned"
        )
        raise typer.Exit(1)

    existing = agent_hub_request("GET", f"/api/memory/episode/{uuid}", tool_name="st memory update")
    if "detail" in existing:
        typer.echo(f"Error: {existing['detail']}")
        raise typer.Exit(1)

    full_uuid = existing.get("uuid", uuid)
    old_tier = existing.get("injection_tier", "reference")
    old_content = existing.get("content", "")

    content_or_tier_changed = bool(content or tier)
    properties_changed = bool(trigger_types or pinned is not None)

    if confirm:
        typer.echo(f"  UUID: {uuid[:8]}...")
        if tier:
            typer.echo(f"  Tier: {old_tier} -> {tier}")
        if content:
            typer.echo(f"  Content: {old_content[:40]}... -> {content[:40]}...")
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
            if trigger_types:
                typer.echo(f"  Trigger types: {props['trigger_task_types']}")
            if pinned is not None:
                typer.echo(f"  Pinned: {pinned}")

    if not content_or_tier_changed and not properties_changed:
        typer.echo("No changes made.")


def batch_tier_impl(
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
        updates = json_lib.loads(input_file.read_text())
    elif json_input:
        updates = json_lib.loads(json_input)
    elif tier and uuids:
        updates = [{"uuid": u, "tier": tier} for u in uuids]
    else:
        typer.echo("Error: Provide --file, --json, or (UUIDs with --tier)")
        raise typer.Exit(1)

    if not updates:
        typer.echo("Error: No updates provided")
        raise typer.Exit(1)

    result = agent_hub_request(
        "POST",
        "/api/memory/batch-update-tier",
        json={"updates": updates},
        tool_name="st memory batch-tier",
    )

    if is_compact():
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
    limit: int,
    uuids: list[str] | None,
    output: Path | None,
    scope: str,
    scope_id: str | None,
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
        params: dict[str, Any] = {"limit": limit}
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

        cursor = result.get("cursor")
        while cursor and len(episodes) < limit:
            params["cursor"] = cursor
            result = agent_hub_request(
                "GET",
                "/api/memory/list",
                params=params,
                scope=scope,
                scope_id=scope_id,
                tool_name="st memory export",
            )
            episodes.extend(result.get("episodes", []))
            cursor = result.get("cursor")
            if not result.get("has_more"):
                break

    export_data = {
        "exported_at": datetime.datetime.now().isoformat(),
        "count": len(episodes),
        "episodes": episodes,
    }

    json_output = json_lib.dumps(export_data, indent=2, default=str)

    if output:
        output.write_text(json_output)
        typer.echo(f"Exported {len(episodes)} episodes to {output}")
    else:
        typer.echo(json_output)


def import_impl(input_file: Path, dry_run: bool) -> None:
    if not input_file.exists():
        output_error(f"File not found: {input_file}")
        raise typer.Exit(1)

    data = json_lib.loads(input_file.read_text())
    episodes = data.get("episodes", [])

    if not episodes:
        typer.echo("No episodes to import")
        return

    updates: list[dict[str, Any]] = []
    for ep in episodes:
        uuid = ep.get("uuid")
        if not uuid:
            continue

        update: dict[str, Any] = {"uuid": uuid}
        if ep.get("injection_tier"):
            update["injection_tier"] = ep["injection_tier"]
        if ep.get("summary") is not None:
            update["summary"] = ep["summary"]
        if ep.get("trigger_task_types") is not None:
            update["trigger_task_types"] = ep["trigger_task_types"]
        if ep.get("pinned") is not None:
            update["pinned"] = ep["pinned"]
        if ep.get("auto_inject") is not None:
            update["auto_inject"] = ep["auto_inject"]
        if ep.get("display_order") is not None:
            update["display_order"] = ep["display_order"]

        if len(update) > 1:
            updates.append(update)

    if dry_run:
        typer.echo(f"DRY RUN: Would update {len(updates)} episodes")
        for u in updates[:10]:
            fields = [k for k in u if k != "uuid"]
            typer.echo(f"  {u['uuid'][:8]}: {', '.join(fields)}")
        if len(updates) > 10:
            typer.echo(f"  ... and {len(updates) - 10} more")
        return

    if not updates:
        typer.echo("No updates needed")
        return

    result = agent_hub_request(
        "POST",
        "/api/memory/batch-update",
        json={"updates": updates},
        tool_name="st memory import",
    )

    if is_compact():
        updated = result.get("updated", 0)
        failed = result.get("failed", 0)
        typer.echo(f"IMPORT[{len(updates)}]:updated={updated}|failed={failed}")
    else:
        typer.echo(f"Updated: {result.get('updated', 0)}/{result.get('total', 0)}")
        if result.get("failed", 0) > 0:
            typer.echo("Failed updates:")
            for r in result.get("results", []):
                if not r.get("success"):
                    typer.echo(f"  {r['uuid'][:8]}: {r.get('error', 'Unknown')}")


def cleanup_impl(
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
        if is_compact():
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
        if is_compact():
            format_stale_cleanup_compact(result)
        else:
            output_json(result)
