"""Tests for project pulse service filtering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_build_project_pulse_separates_stale_sessions_from_live_coordination() -> None:
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
                "live_activity": {"phase": "waiting_for_model", "health": "quiet", "lifecycle_state": "quiet"},
            },
            {
                "id": "sess-stale",
                "status": "active",
                "session_type": "claude_code",
                "updated_at": stale,
                "live_activity": {"phase": "waiting_for_model", "health": "stalled", "lifecycle_state": "reapable", "reapable": True},
            },
            {
                "id": "sess-live",
                "status": "active",
                "session_type": "agent",
                "updated_at": stale,
                "live_activity": {"phase": "waiting_for_model", "health": "stalled", "lifecycle_state": "stalled"},
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
    assert [session["id"] for session in payload["stale_sessions"]] == ["sess-stale"]
    assert payload["summary"]["active_sessions"] == 2
    assert payload["summary"]["stale_sessions"] == 1
    assert payload["summary"]["reapable_sessions"] == 1


@pytest.mark.asyncio
async def test_build_project_pulse_prefers_richer_active_session_over_tmux_presence_duplicate() -> None:
    fresh = (datetime.now(UTC) - timedelta(seconds=15)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "tmux:codex-terminal",
                "status": "active",
                "provider": "codex",
                "model": "codex/external-tmux",
                "session_type": "agent",
                "current_branch": "main",
                "working_dir": "/home/kasadis/terminal",
                "worktree_path": "/home/kasadis/terminal",
                "repo_root": "/home/kasadis/terminal",
                "updated_at": fresh,
                "live_activity": {"phase": "waiting_for_model", "health": "active", "lifecycle_state": "active"},
            },
            {
                "id": "sess-codex-rich",
                "status": "active",
                "provider": "codex",
                "model": "codex/gpt-5.4",
                "session_type": "agent",
                "current_branch": "main",
                "working_dir": "/home/kasadis/terminal",
                "worktree_path": "/home/kasadis/terminal",
                "repo_root": "/home/kasadis/terminal",
                "updated_at": fresh,
                "live_activity": {"phase": "waiting_for_model", "health": "active", "lifecycle_state": "active"},
            },
            {
                "id": "tmux:claude-terminal",
                "status": "active",
                "provider": "anthropic",
                "model": "claude/external-tmux",
                "session_type": "claude_code",
                "current_branch": "main",
                "working_dir": "/home/kasadis/terminal",
                "worktree_path": "/home/kasadis/terminal",
                "repo_root": "/home/kasadis/terminal",
                "updated_at": fresh,
                "live_activity": {"phase": "waiting_for_model", "health": "active", "lifecycle_state": "active"},
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
                "project_id": "terminal",
                "active_worktrees": 0,
                "dirty_worktrees": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("terminal")

    assert [session["id"] for session in payload["active_sessions"]] == [
        "sess-codex-rich",
        "tmux:claude-terminal",
    ]
    assert payload["summary"]["active_sessions"] == 2


@pytest.mark.asyncio
async def test_build_project_pulse_preserves_session_request_identity_fields() -> None:
    fresh = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-observer",
                "status": "active",
                "session_type": "agent",
                "request_source": "codex-transcript-sync",
                "source_client": "summitflow/codex-session-sync",
                "source_path": "/home/kasadis/bin/codex-session-sync.py",
                "updated_at": fresh,
                "live_activity": {"phase": "waiting_for_model", "health": "quiet", "lifecycle_state": "quiet"},
            }
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

    observer = payload["active_sessions"][0]
    assert observer["request_source"] == "codex-transcript-sync"
    assert observer["source_client"] == "summitflow/codex-session-sync"
    assert observer["source_path"] == "/home/kasadis/bin/codex-session-sync.py"
