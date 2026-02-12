"""Change detection logic for memory import."""

from __future__ import annotations

from typing import Any

from .memory_api import agent_hub_request


def fetch_current_episodes() -> dict[str, dict[str, Any]]:
    """Fetch current episodes from memory system."""
    current_result = agent_hub_request(
        "GET",
        "/api/memory/list",
        params={"limit": 300},
        tool_name="st memory import",
    )
    current_episodes = current_result.get("episodes", [])
    return {ep["uuid"]: ep for ep in current_episodes}


def detect_content_changes(
    imported_by_uuid: dict[str, dict[str, Any]],
    current_by_uuid: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect episodes where content has changed."""
    content_changes: list[dict[str, Any]] = []

    for uuid, imported_ep in imported_by_uuid.items():
        current_ep = current_by_uuid.get(uuid)
        if not current_ep:
            continue

        imported_content = imported_ep.get("content", "")
        current_content = current_ep.get("content", "")

        if imported_content != current_content:
            content_changes.append({
                "uuid": uuid,
                "old_content": current_content,
                "new_content": imported_content,
                "name": current_ep.get("name", "imported_episode"),
                "tier": imported_ep.get("category") or current_ep.get("injection_tier", "reference"),
            })

    return content_changes


def detect_property_updates(
    imported_by_uuid: dict[str, dict[str, Any]],
    current_by_uuid: dict[str, dict[str, Any]],
    content_changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect episodes where properties (but not content) have changed."""
    content_change_uuids = {c["uuid"] for c in content_changes}
    property_updates: list[dict[str, Any]] = []

    for uuid, imported_ep in imported_by_uuid.items():
        if uuid in content_change_uuids:
            continue

        current_ep = current_by_uuid.get(uuid)
        if not current_ep:
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

    return property_updates
