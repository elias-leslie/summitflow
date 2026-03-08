"""Tests for project pulse service filtering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_build_project_pulse_filters_stale_observer_sessions() -> None:
    fresh = (datetime.now(UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    stale = (datetime.now(UTC) - timedelta(hours=6)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-fresh",
                "status": "active",
                "session_type": "claude_code",
                "updated_at": fresh,
                "live_activity": None,
            },
            {
                "id": "sess-stale",
                "status": "active",
                "session_type": "claude_code",
                "updated_at": stale,
                "live_activity": None,
            },
            {
                "id": "sess-live",
                "status": "active",
                "session_type": "agent",
                "updated_at": stale,
                "live_activity": {"phase": "waiting_for_model", "health": "stalled"},
            },
        ]
    }

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch("app.services.project_pulse.list_tasks", return_value=[]),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "agent-hub",
                "active_worktrees": 0,
                "dirty_worktrees": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("agent-hub")

    assert [session["id"] for session in payload["active_sessions"]] == ["sess-fresh", "sess-live"]
    assert payload["summary"]["active_sessions"] == 2
