"""Agent Hub-owned automation profile lookup for legacy clock fencing."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx

from ._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers


def legacy_clock_owns(project_id: str, workflow_key: str) -> bool:
    """Allow a local cron tick only when one central profile says legacy owns it."""
    secret = os.environ.get("INTERNAL_SERVICE_SECRET", "").strip()
    if not secret:
        return False
    try:
        response = httpx.get(
            f"{AGENT_HUB_URL.rstrip('/')}/api/automations/profiles",
            params={"project_id": project_id},
            headers=build_agent_hub_headers(
                request_source="summitflow-automation-clock",
                extra_headers={"X-Agent-Hub-Internal": secret},
            ),
            timeout=5.0,
        )
        response.raise_for_status()
        payload: Any = response.json()
    except Exception:
        return False

    profiles = payload.get("items") if isinstance(payload, Mapping) else payload
    if not isinstance(profiles, list):
        return False
    full_key = f"summitflow/{workflow_key}"
    matches = [
        item
        for item in profiles
        if (
            isinstance(item, Mapping)
            and item.get("project_id") == project_id
            and item.get("workflow_key") == full_key
        )
    ]
    return len(matches) == 1 and matches[0].get("clock_owner") == "legacy"
