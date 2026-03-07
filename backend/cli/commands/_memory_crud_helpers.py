"""Helper functions for memory CRUD operations."""

from __future__ import annotations

import typer

from .memory_api import agent_hub_request
from .memory_validation import validate_summary_length


def build_save_payload(
    content: str,
    summary: str,
    tier: str,
    confidence: int,
    context: str | None,
    pinned: bool,
    trigger_types: str | None,
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
        payload["trigger_task_types"] = [t.strip() for t in trigger_types.split(",")]
    return payload


def parse_tags_csv(tags: str | None) -> list[str] | None:
    """Parse comma-separated tags into a deduplicated sorted list."""
    if tags is None:
        return None
    parsed = sorted({tag.strip() for tag in tags.split(",") if tag.strip()})
    return parsed


def validate_save_inputs(tier: str, confidence: int, summary: str) -> str:
    """Validate save inputs and return stripped summary, raise on error."""
    from ..output import output_error

    if tier not in ("mandate", "guardrail", "reference"):
        output_error(f"Invalid tier: {tier}. Must be mandate, guardrail, or reference.")
        raise typer.Exit(1)
    if confidence < 0 or confidence > 100:
        output_error(f"Invalid confidence: {confidence}. Must be 0-100.")
        raise typer.Exit(1)
    if not summary or not summary.strip():
        output_error("--summary is required. Provide a short action phrase (~35 chars).")
        raise typer.Exit(1)
    stripped = summary.strip()
    validate_summary_length(stripped)
    return stripped


def fetch_existing_episode(uuid: str) -> dict[str, object]:
    """Fetch an existing episode, raising on error."""
    existing = agent_hub_request("GET", f"/api/memory/episode/{uuid}", tool_name="st memory update")
    if "detail" in existing:
        typer.echo(f"Error: {existing['detail']}")
        raise typer.Exit(1)
    return existing


def fetch_episode_tags(uuid: str) -> list[str]:
    """Fetch current tags for an episode."""
    result = agent_hub_request("GET", f"/api/memory/episodes/{uuid}/tags", tool_name="st memory update")
    return [str(tag) for tag in result.get("tags", [])]


def replace_episode(
    old_uuid: str,
    new_content: str,
    new_tier: str,
    existing: dict[str, object],
) -> str:
    """Create a new episode and delete the old one. Returns new UUID."""
    full_uuid = str(existing.get("uuid", old_uuid))

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

    _delete_with_retry(old_uuid, str(new_uuid))
    return str(new_uuid)


def _delete_with_retry(uuid: str, new_uuid: str) -> None:
    """Delete episode with one retry on failure."""
    delete_result: dict[str, object] = {}
    for attempt in range(2):
        try:
            delete_result = agent_hub_request(
                "DELETE", f"/api/memory/episode/{uuid}", tool_name="st memory update"
            )
            if delete_result.get("success"):
                return
        except SystemExit:
            if attempt == 0:
                typer.echo("  Retrying delete...")
                continue
            raise

    typer.echo(f"Warning: Failed to delete original: {delete_result.get('detail', 'Unknown')}")
    typer.echo(f"New episode created: {new_uuid[:8]}")
    typer.echo(f"Please manually delete: {uuid[:8]}")
    raise typer.Exit(1)


def patch_episode_properties(
    target_uuid: str,
    summary: str | None,
    trigger_types: str | None,
    pinned: bool | None,
) -> None:
    """Patch episode properties and echo results."""
    props: dict[str, object] = {}
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
        typer.echo(f"Warning: Failed to update properties: {patch_result.get('message', 'Unknown')}")
        return

    if summary:
        typer.echo(f"  Summary: {summary}")
    if trigger_types:
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
