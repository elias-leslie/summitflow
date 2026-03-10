"""CRUD operations for memory system."""

from __future__ import annotations

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext
from ._memory_crud_helpers import (
    build_save_payload,
    fetch_episode_tags,
    fetch_existing_episode,
    parse_tags_csv,
    patch_episode_properties,
    replace_episode_tags,
    update_episode_content_or_tier,
    validate_save_inputs,
)
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
        "GET", "/api/memory/stats", scope=scope, scope_id=scope_id, tool_name="st memory stats"
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
    tags: str | None,
    scope: str,
    scope_id: str | None,
) -> None:
    summary = validate_save_inputs(tier, confidence, summary)
    validate_content_format(content, summary)
    payload = build_save_payload(content, summary, tier, confidence, context, pinned, trigger_types)
    result = agent_hub_request(
        "POST", "/api/memory/save-learning", json=payload,
        scope=scope, scope_id=scope_id, tool_name="st memory save",
    )
    parsed_tags = parse_tags_csv(tags)
    if parsed_tags is not None and result.get("uuid"):
        replace_episode_tags(str(result["uuid"]), parsed_tags)
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
    params: dict[str, object] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if tier:
        params["category"] = tier
    result = agent_hub_request(
        "GET", "/api/memory/list", params=params,
        scope=scope, scope_id=scope_id, tool_name="st memory list",
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
    params: dict[str, object] = {"query": query, "limit": limit, "min_score": min_score}
    result = agent_hub_request(
        "GET", "/api/memory/search", params=params,
        scope=scope, scope_id=scope_id, tool_name="st memory search",
    )
    if out.is_compact:
        format_search_compact(result)
    else:
        output_json(result)


def get_impl(out: OutputContext, uuids: list[str]) -> None:
    if not uuids:
        output_error("At least one UUID required")
        raise typer.Exit(1)

    if len(uuids) > 1:
        result = agent_hub_request(
            "POST", "/api/memory/batch-get", json={"uuids": uuids}, tool_name="st memory get"
        )
        if out.is_compact:
            format_batch_get_compact(result)
        else:
            output_json(result)
        return

    result = agent_hub_request("GET", f"/api/memory/episode/{uuids[0]}", tool_name="st memory get")
    if "detail" in result:
        output_error(result["detail"])
        raise typer.Exit(1)
    if out.is_compact:
        format_get_compact(result)
    else:
        output_json(result)


def delete_impl(uuids: list[str]) -> None:
    if len(uuids) == 1:
        _delete_single(uuids[0])
        return
    result = agent_hub_request(
        "POST", "/api/memory/bulk-delete", json={"ids": uuids}, tool_name="st memory delete"
    )
    for error in result.get("errors", []):
        typer.echo(f"Failed: {error['id'][:8]} - {error.get('error', 'Unknown')}")
    typer.echo(f"\nDeleted: {result.get('deleted', 0)}, Failed: {result.get('failed', 0)}")


def _delete_single(uuid: str) -> None:
    result = agent_hub_request(
        "DELETE", f"/api/memory/episode/{uuid}", tool_name="st memory delete"
    )
    if result.get("success"):
        typer.echo(f"Deleted: {uuid[:8]}")
        typer.echo("\nDeleted: 1, Failed: 0")
    else:
        typer.echo(f"Failed: {uuid[:8]} - {result.get('detail', 'Unknown error')}")
        typer.echo("\nDeleted: 0, Failed: 1")


def update_impl(
    uuid: str,
    content: str | None,
    tier: str | None,
    summary: str | None,
    trigger_types: str | None,
    pinned: bool | None,
    tags: str | None,
    clear_tags: bool,
) -> None:
    if tags and clear_tags:
        typer.echo("Error: Specify only one of --tags or --clear-tags")
        raise typer.Exit(1)

    if not any([content, tier, summary, trigger_types, pinned is not None, tags is not None, clear_tags]):
        typer.echo(
            "Error: Must specify at least one of: --content, --tier, --summary, --trigger-types, --pinned, --tags, --clear-tags"
        )
        raise typer.Exit(1)

    if summary:
        validate_summary_length(summary)

    existing = fetch_existing_episode(uuid)
    existing_tags = fetch_episode_tags(uuid)
    replacement_tags = [] if clear_tags else parse_tags_csv(tags)
    content_or_tier_changed = bool(content or tier)
    properties_changed = bool(summary or trigger_types or pinned is not None)
    tags_changed = replacement_tags is not None or clear_tags

    if content:
        validate_content_format(content, summary or str(existing.get("summary", "")))

    target_uuid = str(existing.get("uuid", uuid))

    if content_or_tier_changed:
        new_content = content if content else str(existing.get("content", ""))
        new_tier = tier if tier else str(existing.get("injection_tier", "reference"))
        update_episode_content_or_tier(
            target_uuid,
            content=new_content,
            tier=new_tier,
        )
        replace_episode_tags(target_uuid, replacement_tags if replacement_tags is not None else existing_tags)

    if properties_changed:
        patch_episode_properties(target_uuid, summary, trigger_types, pinned)

    if not content_or_tier_changed and tags_changed:
        replace_episode_tags(target_uuid, replacement_tags or [])

    if not content_or_tier_changed and not properties_changed and not tags_changed:
        typer.echo("No changes made.")
