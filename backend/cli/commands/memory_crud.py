"""CRUD operations for memory system."""

from __future__ import annotations

from typing import Any

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext
from .memory_api import agent_hub_request
from .memory_formatters import (
    format_batch_get_compact,
    format_get_compact,
    format_list_compact,
    format_save_compact,
    format_search_compact,
    format_stats_compact,
)
from .memory_validation import validate_content_format, validate_summary_length


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
    validate_summary_length(summary)
    validate_content_format(content, summary)

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

    if summary:
        validate_summary_length(summary)

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
        validate_content_format(content, effective_summary)

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
