"""Apply import changes to memory system."""

from __future__ import annotations

from typing import Any

import typer

from .memory_api import agent_hub_request


def apply_content_changes(content_changes: list[dict[str, Any]]) -> tuple[int, int]:
    """Apply content changes (create new + delete old). Returns (success, failed)."""
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

    return content_success, content_failed


def apply_property_updates(property_updates: list[dict[str, Any]]) -> tuple[int, int]:
    """Apply property updates via batch API. Returns (updated, failed)."""
    if not property_updates:
        return 0, 0

    result = agent_hub_request(
        "POST",
        "/api/memory/batch-update",
        json={"updates": property_updates},
        tool_name="st memory import",
    )
    return result.get("updated", 0), result.get("failed", 0)
