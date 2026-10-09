"""Agent Hub-owned automation profile lookup for legacy clock fencing."""

from __future__ import annotations

import os
from collections.abc import Mapping

from ._agent_hub_config import get_sync_client

_PROFILE_LIMIT = 500


def legacy_clock_owns(project_id: str, workflow_key: str) -> bool:
    """Allow a local cron tick only when one central profile says legacy owns it."""
    secret = os.environ.get("INTERNAL_SERVICE_SECRET", "").strip()
    if not secret:
        return False
    try:
        with get_sync_client(timeout=5.0, client_name="summitflow-automation-clock") as client:
            profiles = client.list_automation_profiles(
                project_id, internal_secret=secret, limit=_PROFILE_LIMIT
            )
    except Exception:
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
