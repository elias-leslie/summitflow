"""CRUD operations for memory system."""

from __future__ import annotations

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext
from ._memory_crud_helpers import (
    build_save_payload,
    fetch_episode_tags,
    fetch_existing_episode,
    parse_csv_values,
    parse_tags_csv,
    patch_episode_properties,
    replace_episode_tags,
    update_episode_content_or_tier,
    validate_save_inputs,
    validate_summary_input,
    validate_tier,
)
from .memory_api import agent_hub_request
from .memory_formatters import (
    format_batch_get_compact,
    format_get_compact,
    format_list_compact,
    format_restore_compact,
    format_revisions_compact,
    format_save_compact,
    format_search_compact,
    format_stats_compact,
)
from .memory_validation import validate_content_format, validate_episode_content_present


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
    change_reason: str | None = None,
) -> None:
    summary = validate_save_inputs(tier, confidence, summary)
    validate_episode_content_present(content)
    validate_content_format(content, summary, tier)
    payload = build_save_payload(content, summary, tier, confidence, context, pinned, trigger_types, change_reason)
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
    if out.is_compact:
        format_get_compact(result)
    else:
        output_json(result)


def delete_impl(uuids: list[str], *, change_reason: str | None = None) -> None:
    if len(uuids) == 1:
        _delete_single(uuids[0], change_reason=change_reason)
        return
    result = agent_hub_request(
        "POST",
        "/api/memory/bulk-delete",
        json={"ids": uuids, "change_reason": change_reason},
        tool_name="st memory delete",
    )
    for error in result.get("errors", []):
        typer.echo(f"Failed: {error['id'][:8]} - {error.get('error', 'Unknown')}")
    typer.echo(f"\nDeleted: {result.get('deleted', 0)}, Failed: {result.get('failed', 0)}")


def _delete_single(uuid: str, *, change_reason: str | None = None) -> None:
    result = agent_hub_request(
        "DELETE",
        f"/api/memory/episode/{uuid}",
        params={"change_reason": change_reason} if change_reason else None,
        tool_name="st memory delete",
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
    change_reason: str | None = None,
) -> None:
    if tags and clear_tags:
        typer.echo("Error: Specify only one of --tags or --clear-tags")
        raise typer.Exit(1)

    if not any(
        [content is not None, tier is not None, summary is not None, trigger_types is not None, pinned is not None, tags is not None, clear_tags]
    ):
        typer.echo(
            "Error: Must specify at least one of: --content, --tier, --summary, --trigger-types, --pinned, --tags, --clear-tags"
        )
        raise typer.Exit(1)

    if content is not None:
        validate_episode_content_present(content)

    normalized_summary = validate_summary_input(summary, required=False) if summary is not None else None
    normalized_tier = validate_tier(tier) if tier is not None else None
    replacement_tags = [] if clear_tags else parse_tags_csv(tags)
    content_or_tier_changed = content is not None or normalized_tier is not None
    properties_changed = normalized_summary is not None or trigger_types is not None or pinned is not None
    tags_changed = replacement_tags is not None or clear_tags

    existing: dict[str, object] | None = None
    existing_tags: list[str] = []
    effective_tier = normalized_tier

    if content_or_tier_changed:
        existing = fetch_existing_episode(uuid)
        effective_tier = normalized_tier or str(existing.get("injection_tier", "reference"))

    if content is not None:
        assert existing is not None
        validate_content_format(content, normalized_summary or str(existing.get("summary", "")), effective_tier)

    target_uuid = str(existing.get("uuid", uuid)) if existing else uuid

    if content_or_tier_changed and replacement_tags is None:
        existing_tags = fetch_episode_tags(uuid)

    if content_or_tier_changed:
        assert existing is not None
        new_content = content if content is not None else str(existing.get("content", ""))
        if change_reason is None:
            update_episode_content_or_tier(
                target_uuid,
                content=new_content,
                tier=effective_tier,
            )
        else:
            update_episode_content_or_tier(
                target_uuid,
                content=new_content,
                tier=effective_tier,
                change_reason=change_reason,
            )
        replace_episode_tags(target_uuid, replacement_tags if replacement_tags is not None else existing_tags)

    if properties_changed:
        normalized_trigger_types = None
        if trigger_types is not None:
            normalized_trigger_types = ",".join(parse_csv_values(trigger_types) or [])
        if change_reason is None:
            patch_episode_properties(
                target_uuid,
                normalized_summary,
                normalized_trigger_types,
                pinned,
            )
        else:
            patch_episode_properties(
                target_uuid,
                normalized_summary,
                normalized_trigger_types,
                pinned,
                change_reason=change_reason,
            )

    if not content_or_tier_changed and tags_changed:
        replace_episode_tags(target_uuid, replacement_tags or [])

    if not content_or_tier_changed and not properties_changed and not tags_changed:
        typer.echo("No changes made.")


def revisions_impl(out: OutputContext, uuid: str, limit: int) -> None:
    """Fetch immutable revision history for one memory episode."""
    result = agent_hub_request(
        "GET",
        f"/api/memory/episode/{uuid}/revisions",
        params={"limit": limit},
        tool_name="st memory revisions",
    )
    if out.is_compact:
        format_revisions_compact(uuid, result)
    else:
        output_json(result)


def restore_impl(uuid: str, revision_id: str, *, change_reason: str | None = None) -> None:
    """Restore a memory episode to one historical revision."""
    payload = {"change_reason": change_reason} if change_reason else {}
    result = agent_hub_request(
        "POST",
        f"/api/memory/episode/{uuid}/revisions/{revision_id}/restore",
        json=payload,
        tool_name="st memory restore",
    )
    format_restore_compact(uuid, revision_id, result)
