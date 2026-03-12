"""Helper functions for memory CRUD operations."""

from __future__ import annotations

import typer

from .memory_api import agent_hub_request
from .memory_validation import validate_summary_length

VALID_TIERS = ("mandate", "guardrail", "reference")


def parse_csv_values(raw: str | None) -> list[str] | None:
    """Parse comma-separated values, preserving order while deduplicating."""
    if raw is None:
        return None
    values: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        cleaned = part.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        values.append(cleaned)
    return values


def validate_tier(tier: str) -> str:
    """Validate tier value and return the normalized string."""
    from ..output import output_error

    normalized = tier.strip()
    if normalized not in VALID_TIERS:
        output_error(f"Invalid tier: {tier}. Must be mandate, guardrail, or reference.")
        raise typer.Exit(1)
    return normalized


def validate_summary_input(summary: str, *, required: bool) -> str:
    """Normalize summary text and enforce presence and max length."""
    from ..output import output_error

    normalized = summary.strip()
    if required and not normalized:
        output_error("--summary is required. Provide a short action phrase (~35 chars).")
        raise typer.Exit(1)
    if not normalized:
        output_error("Summary cannot be blank.")
        raise typer.Exit(1)
    validate_summary_length(normalized)
    return normalized


def build_save_payload(
    content: str,
    summary: str,
    tier: str,
    confidence: int,
    context: str | None,
    pinned: bool,
    trigger_types: str | None,
    change_reason: str | None,
) -> dict[str, object]:
    """Build the payload dict for save-learning request."""
    payload: dict[str, object] = {
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
        parsed_trigger_types = parse_csv_values(trigger_types)
        if parsed_trigger_types:
            payload["trigger_task_types"] = parsed_trigger_types
    if change_reason:
        payload["change_reason"] = change_reason
    return payload


def parse_tags_csv(tags: str | None) -> list[str] | None:
    """Parse comma-separated tags into a deduplicated list."""
    return parse_csv_values(tags)


def validate_save_inputs(tier: str, confidence: int, summary: str) -> str:
    """Validate save inputs and return stripped summary, raise on error."""
    from ..output import output_error

    validate_tier(tier)
    if confidence < 0 or confidence > 100:
        output_error(f"Invalid confidence: {confidence}. Must be 0-100.")
        raise typer.Exit(1)
    return validate_summary_input(summary, required=True)


def fetch_existing_episode(uuid: str) -> dict[str, object]:
    """Fetch an existing episode, raising on error."""
    return agent_hub_request("GET", f"/api/memory/episode/{uuid}", tool_name="st memory update")


def fetch_episode_tags(uuid: str) -> list[str]:
    """Fetch current tags for an episode."""
    result = agent_hub_request("GET", f"/api/memory/episodes/{uuid}/tags", tool_name="st memory update")
    return [str(tag) for tag in result.get("tags", [])]


def update_episode_content_or_tier(
    episode_uuid: str,
    *,
    content: str | None,
    tier: str | None,
    change_reason: str | None = None,
) -> None:
    """Patch episode content and/or tier in place while preserving UUID."""
    payload: dict[str, object] = {}
    if content is not None:
        payload["content"] = content
    if tier is not None:
        payload["injection_tier"] = tier
    if change_reason:
        payload["change_reason"] = change_reason

    result = agent_hub_request(
        "PATCH",
        f"/api/memory/episode/{episode_uuid}",
        json=payload,
        tool_name="st memory update",
    )
    if not result.get("success"):
        typer.echo(f"Error updating episode: {result}")
        raise typer.Exit(1)

    typer.echo(f"Updated: {episode_uuid[:8]}")
    if tier is not None:
        typer.echo(f"  Tier: {tier}")


def patch_episode_properties(
    target_uuid: str,
    summary: str | None,
    trigger_types: str | None,
    pinned: bool | None,
    *,
    change_reason: str | None = None,
) -> None:
    """Patch episode properties and echo results."""
    props: dict[str, object] = {}
    if summary is not None:
        props["summary"] = summary
    if trigger_types is not None:
        props["trigger_task_types"] = parse_csv_values(trigger_types) or []
    if pinned is not None:
        props["pinned"] = pinned
    if change_reason:
        props["change_reason"] = change_reason

    patch_result = agent_hub_request(
        "PATCH",
        f"/api/memory/episode/{target_uuid}/properties",
        json=props,
        tool_name="st memory update",
    )

    if not patch_result.get("success"):
        typer.echo(f"Warning: Failed to update properties: {patch_result.get('message', 'Unknown')}")
        return

    if summary is not None:
        typer.echo(f"  Summary: {summary}")
    if trigger_types is not None:
        typer.echo(f"  Trigger types: {props['trigger_task_types']}")
    if pinned is not None:
        typer.echo(f"  Pinned: {pinned}")


def replace_episode_tags(target_uuid: str, tags: list[str]) -> None:
    """Replace tags on an episode."""
    result = agent_hub_request(
        "PUT",
        f"/api/memory/episodes/{target_uuid}/tags",
        json={"tags": tags},
        tool_name="st memory update",
    )
    if result.get("tags") != tags:
        typer.echo(f"Warning: Failed to update tags on {target_uuid[:8]}")
        return
    typer.echo(f"  Tags: {', '.join(tags) if tags else '(cleared)'}")
