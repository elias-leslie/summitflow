"""Helper functions for memory CRUD operations."""

from __future__ import annotations

import typer

from ._api_paths import (
    MEMORY_EPISODE_PATH,
    MEMORY_EPISODE_PROPERTIES_PATH,
    MEMORY_EPISODE_TAGS_PATH,
)
from .memory_api import agent_hub_request
from .memory_validation import validate_episode_content_present, validate_summary_length

VALID_TIERS = ("mandate", "guardrail", "reference")
VALID_CONTEXT_KINDS = ("policy", "reference", "capability", "continuity", "signal")


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


def validate_context_kind(context_kind: str) -> str:
    """Validate context kind value and return the normalized string."""
    from ..output import output_error

    normalized = context_kind.strip()
    if normalized not in VALID_CONTEXT_KINDS:
        output_error(
            f"Invalid context kind: {context_kind}. Must be policy, reference, capability, continuity, or signal."
        )
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
    trigger_phases: str | None,
    context_kind: str | None,
    consumer_profiles: str | None,
    exclude_consumer_profiles: str | None,
    agent_slugs: str | None,
    exclude_agent_slugs: str | None,
    audience_tags: str | None,
    exclude_audience_tags: str | None,
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
    if trigger_phases is not None:
        payload["trigger_phases"] = parse_csv_values(trigger_phases) or []
    if context_kind is not None:
        payload["context_kind"] = validate_context_kind(context_kind)
    applicability = build_applicability_payload(
        consumer_profiles=consumer_profiles,
        exclude_consumer_profiles=exclude_consumer_profiles,
        agent_slugs=agent_slugs,
        exclude_agent_slugs=exclude_agent_slugs,
        audience_tags=audience_tags,
        exclude_audience_tags=exclude_audience_tags,
    )
    if applicability is not None:
        payload["applicability"] = applicability
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


def build_applicability_payload(
    *,
    consumer_profiles: str | None,
    exclude_consumer_profiles: str | None,
    agent_slugs: str | None,
    exclude_agent_slugs: str | None,
    audience_tags: str | None,
    exclude_audience_tags: str | None,
) -> dict[str, list[str]] | None:
    """Build applicability payload from CLI CSV options."""
    applicability = {
        "consumer_profiles": parse_csv_values(consumer_profiles) or [],
        "exclude_consumer_profiles": parse_csv_values(exclude_consumer_profiles) or [],
        "agent_slugs": parse_csv_values(agent_slugs) or [],
        "exclude_agent_slugs": parse_csv_values(exclude_agent_slugs) or [],
        "audience_tags": parse_csv_values(audience_tags) or [],
        "exclude_audience_tags": parse_csv_values(exclude_audience_tags) or [],
    }
    if not any(applicability.values()):
        return None
    return applicability


def merge_applicability_payload(
    existing_episode: dict[str, object] | None,
    *,
    consumer_profiles: str | None,
    exclude_consumer_profiles: str | None,
    agent_slugs: str | None,
    exclude_agent_slugs: str | None,
    audience_tags: str | None,
    exclude_audience_tags: str | None,
    clear_applicability: bool,
) -> dict[str, list[str]] | None:
    """Merge CLI applicability updates with an existing episode payload."""
    if clear_applicability:
        return {}

    existing_raw = existing_episode.get("applicability") if isinstance(existing_episode, dict) else {}
    base = dict(existing_raw) if isinstance(existing_raw, dict) else {}
    merged: dict[str, list[str]] = {
        "consumer_profiles": list(base.get("consumer_profiles") or []),
        "exclude_consumer_profiles": list(base.get("exclude_consumer_profiles") or []),
        "agent_slugs": list(base.get("agent_slugs") or []),
        "exclude_agent_slugs": list(base.get("exclude_agent_slugs") or []),
        "audience_tags": list(base.get("audience_tags") or []),
        "exclude_audience_tags": list(base.get("exclude_audience_tags") or []),
    }

    updates = {
        "consumer_profiles": consumer_profiles,
        "exclude_consumer_profiles": exclude_consumer_profiles,
        "agent_slugs": agent_slugs,
        "exclude_agent_slugs": exclude_agent_slugs,
        "audience_tags": audience_tags,
        "exclude_audience_tags": exclude_audience_tags,
    }
    for key, raw in updates.items():
        if raw is not None:
            merged[key] = parse_csv_values(raw) or []
    return merged


def fetch_existing_episode(uuid: str) -> dict[str, object]:
    """Fetch an existing episode, raising on error."""
    return agent_hub_request("GET", MEMORY_EPISODE_PATH.format(uuid=uuid), tool_name="st memory update")


def fetch_episode_tags(uuid: str) -> list[str]:
    """Fetch current tags for an episode."""
    result = agent_hub_request("GET", MEMORY_EPISODE_TAGS_PATH.format(uuid=uuid), tool_name="st memory update")
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
        MEMORY_EPISODE_PATH.format(uuid=episode_uuid),
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
    trigger_phases: str | None,
    pinned: bool | None,
    context_kind: str | None,
    applicability: dict[str, list[str]] | None,
    *,
    change_reason: str | None = None,
) -> None:
    """Patch episode properties and echo results."""
    props: dict[str, object] = {}
    if summary is not None:
        props["summary"] = summary
    if trigger_types is not None:
        props["trigger_task_types"] = parse_csv_values(trigger_types) or []
    if trigger_phases is not None:
        props["trigger_phases"] = parse_csv_values(trigger_phases) or []
    if pinned is not None:
        props["pinned"] = pinned
    if context_kind is not None:
        props["context_kind"] = validate_context_kind(context_kind)
    if applicability is not None:
        props["applicability"] = applicability
    if change_reason:
        props["change_reason"] = change_reason

    patch_result = agent_hub_request(
        "PATCH",
        MEMORY_EPISODE_PROPERTIES_PATH.format(uuid=target_uuid),
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
    if trigger_phases is not None:
        typer.echo(f"  Trigger phases: {props['trigger_phases']}")
    if pinned is not None:
        typer.echo(f"  Pinned: {pinned}")
    if context_kind is not None:
        typer.echo(f"  Context kind: {props['context_kind']}")
    if applicability is not None:
        typer.echo(f"  Applicability: {applicability}")


def replace_episode_tags(target_uuid: str, tags: list[str]) -> None:
    """Replace tags on an episode."""
    result = agent_hub_request(
        "PUT",
        MEMORY_EPISODE_TAGS_PATH.format(uuid=target_uuid),
        json={"tags": tags},
        tool_name="st memory update",
    )
    if result.get("tags") != tags:
        typer.echo(f"Warning: Failed to update tags on {target_uuid[:8]}")
        return
    typer.echo(f"  Tags: {', '.join(tags) if tags else '(cleared)'}")


def _validate_update_and_normalize(
    content: str | None, tier: str | None, summary: str | None, tags: str | None,
    clear_tags: bool, clear_applicability: bool, trigger_types: str | None,
    trigger_phases: str | None, pinned: bool | None, context_kind: str | None,
    consumer_profiles: str | None, exclude_consumer_profiles: str | None,
    agent_slugs: str | None, exclude_agent_slugs: str | None,
    audience_tags: str | None, exclude_audience_tags: str | None,
) -> tuple[str | None, str | None, list[str] | None]:
    if tags and clear_tags:
        typer.echo("Error: Specify only one of --tags or --clear-tags")
        raise typer.Exit(1)
    _nullable = (content, tier, summary, trigger_types, trigger_phases, pinned, context_kind,
                 consumer_profiles, exclude_consumer_profiles, agent_slugs, exclude_agent_slugs,
                 audience_tags, exclude_audience_tags, tags)
    if not any(f is not None for f in _nullable) and not clear_applicability and not clear_tags:
        typer.echo(
            "Error: Must specify at least one of: --content, --tier, --summary, --trigger-types,"
            " --trigger-phases, --pinned, --context-kind, applicability options, --tags, --clear-tags, --clear-applicability"
        )
        raise typer.Exit(1)
    if content is not None:
        validate_episode_content_present(content)
    return (
        validate_summary_input(summary, required=False) if summary is not None else None,
        validate_tier(tier) if tier is not None else None,
        [] if clear_tags else parse_tags_csv(tags),
    )
