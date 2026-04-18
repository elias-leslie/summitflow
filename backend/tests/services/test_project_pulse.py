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
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
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
                "id": "tmux:codex-a-term",
                "status": "active",
                "provider": "codex",
                "model": "codex/external-tmux",
                "session_type": "agent",
                "current_branch": "main",
                "working_dir": "/home/kasadis/a-term",
                "checkout_path": "/home/kasadis/a-term",
                "repo_root": "/home/kasadis/a-term",
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
                "working_dir": "/home/kasadis/a-term",
                "checkout_path": "/home/kasadis/a-term",
                "repo_root": "/home/kasadis/a-term",
                "updated_at": fresh,
                "live_activity": {"phase": "waiting_for_model", "health": "active", "lifecycle_state": "active"},
            },
            {
                "id": "tmux:claude-a-term",
                "status": "active",
                "provider": "anthropic",
                "model": "claude/external-tmux",
                "session_type": "claude_code",
                "current_branch": "main",
                "working_dir": "/home/kasadis/a-term",
                "checkout_path": "/home/kasadis/a-term",
                "repo_root": "/home/kasadis/a-term",
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
                "project_id": "a-term",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("a-term")

    assert [session["id"] for session in payload["active_sessions"]] == [
        "sess-codex-rich",
        "tmux:claude-a-term",
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
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
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


@pytest.mark.asyncio
async def test_build_project_pulse_excludes_stranded_tasks_from_running_summary() -> None:
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {"sessions": []}

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-stranded",
                    "title": "Refactor dead lane",
                    "status": "running",
                    "task_type": "refactor",
                    "priority": 2,
                    "updated_at": stale,
                }
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "agent-hub",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("agent-hub")

    assert payload["running_tasks"] == []
    assert [task["id"] for task in payload["stranded_tasks"]] == ["task-stranded"]
    assert payload["summary"]["running_tasks"] == 0
    assert payload["summary"]["stranded_tasks"] == 1


@pytest.mark.asyncio
async def test_build_project_pulse_stranded_task_with_unrelated_active_owners() -> None:
    """OWNERSHIP[N] + STRANDED: active owners for other tasks don't protect unowned running tasks."""
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")

    ownership_payload = {
        "active_owners": [
            {"session_id": "sess-owner-a", "task_id": "task-other-a"},
            {"session_id": "sess-owner-b", "task_id": "task-other-b"},
        ],
        "active_specialists": [],
    }
    sessions_payload = {"sessions": []}

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-orphan",
                    "title": "Orphaned running task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                }
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "agent-hub",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("agent-hub")

    assert payload["running_tasks"] == []
    assert [task["id"] for task in payload["stranded_tasks"]] == ["task-orphan"]
    assert payload["summary"]["running_tasks"] == 0
    assert payload["summary"]["stranded_tasks"] == 1
    assert payload["summary"]["active_owners"] == 2


@pytest.mark.asyncio
async def test_build_project_pulse_active_owner_prevents_stranded_classification() -> None:
    """A running task with a live active owner is not classified as stranded."""
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")

    ownership_payload = {
        "active_owners": [
            {"session_id": "sess-owner", "task_id": "task-owned"},
        ],
        "active_specialists": [],
    }
    sessions_payload = {"sessions": []}

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-owned",
                    "title": "Actively owned task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                }
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "agent-hub",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("agent-hub")

    assert [task["id"] for task in payload["running_tasks"]] == ["task-owned"]
    assert payload["stranded_tasks"] == []
    assert payload["summary"]["running_tasks"] == 1
    assert payload["summary"]["stranded_tasks"] == 0


@pytest.mark.asyncio
async def test_build_project_pulse_reapable_counts_lifecycle_state_without_boolean_flag() -> None:
    """A stale session with lifecycle_state=reapable but no boolean flag counts as reapable."""
    stale = (datetime.now(UTC) - timedelta(hours=6)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-reapable-no-flag",
                "status": "active",
                "session_type": "agent",
                "updated_at": stale,
                "live_activity": {"lifecycle_state": "reapable", "health": "stalled"},
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
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("agent-hub")

    assert payload["summary"]["stale_sessions"] == 1
    assert payload["summary"]["reapable_sessions"] == 1


@pytest.mark.asyncio
async def test_build_project_pulse_active_session_with_external_id_prevents_stranded() -> None:
    """Active session with external_id=task-xxx protects that task from stranded classification."""
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    fresh = (datetime.now(UTC) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-wrapper",
                "status": "active",
                "session_type": "claude_code",
                "external_id": "task-wrapper-abc",
                "updated_at": fresh,
                "live_activity": {"lifecycle_state": "active", "health": "active"},
            }
        ]
    }

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-wrapper-abc",
                    "title": "Wrapper dispatched task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                }
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "summitflow",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("summitflow")

    assert [task["id"] for task in payload["running_tasks"]] == ["task-wrapper-abc"]
    assert payload["stranded_tasks"] == []
    assert payload["summary"]["running_tasks"] == 1
    assert payload["summary"]["stranded_tasks"] == 0


@pytest.mark.asyncio
async def test_build_project_pulse_active_session_with_task_branch_prevents_stranded() -> None:
    """Active session with current_branch=task-xxx/main protects that task from stranded classification."""
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    fresh = (datetime.now(UTC) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-branch-worker",
                "status": "active",
                "session_type": "claude_code",
                "current_branch": "task-branch-xyz/main",
                "updated_at": fresh,
                "live_activity": {"lifecycle_state": "active", "health": "active"},
            }
        ]
    }

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-branch-xyz",
                    "title": "Branch-linked task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                }
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "summitflow",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("summitflow")

    assert [task["id"] for task in payload["running_tasks"]] == ["task-branch-xyz"]
    assert payload["stranded_tasks"] == []
    assert payload["summary"]["running_tasks"] == 1
    assert payload["summary"]["stranded_tasks"] == 0


@pytest.mark.asyncio
async def test_build_project_pulse_active_orchestrator_files_touched_prevents_stranded() -> None:
    """An active orchestrator session touching task checkout paths protects those tasks from stranded classification."""
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    fresh = (datetime.now(UTC) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-orchestrator",
                "status": "active",
                "session_type": "claude_code",
                "working_dir": "/srv/workspaces/projects/agent-hub",
                "repo_root": "/srv/workspaces/projects/agent-hub",
                "updated_at": fresh,
                "live_activity": {
                    "lifecycle_state": "active",
                    "health": "active",
                    "last_command": "cd /srv/workspaces/lanes/agent-hub/task-alpha123 && dt --quick --changed-only",
                    "last_write_path": "/srv/workspaces/lanes/agent-hub/task-beta456/backend/app/services/example.py",
                    "files_touched": [
                        "/srv/workspaces/lanes/agent-hub/task-alpha123/backend/app/services/alpha.py",
                        "/srv/workspaces/lanes/agent-hub/task-beta456/backend/app/services/beta.py",
                    ],
                },
            }
        ]
    }

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-alpha123",
                    "title": "Lane-backed alpha task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                },
                {
                    "id": "task-beta456",
                    "title": "Lane-backed beta task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                },
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "agent-hub",
                "active_checkpoints": 2,
                "dirty_checkpoints": 2,
                "needs_cleanup": True,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("agent-hub")

    assert [task["id"] for task in payload["running_tasks"]] == ["task-alpha123", "task-beta456"]
    assert payload["stranded_tasks"] == []
    assert payload["summary"]["running_tasks"] == 2
    assert payload["summary"]["stranded_tasks"] == 0


@pytest.mark.asyncio
async def test_build_project_pulse_active_orchestrator_batch_task_ids_prevent_stranded() -> None:
    """A batch orchestrator session should protect queued second-wave tasks before first file touch."""
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    fresh = (datetime.now(UTC) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-batch",
                "status": "active",
                "session_type": "claude_code",
                "current_branch": "main",
                "working_dir": "/srv/workspaces/projects/summitflow",
                "repo_root": "/srv/workspaces/projects/summitflow",
                "batch_task_ids": ["task-alpha123", "task-beta456"],
                "updated_at": fresh,
                "live_activity": {"lifecycle_state": "active", "health": "active"},
            }
        ]
    }

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-alpha123",
                    "title": "Batch alpha task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                },
                {
                    "id": "task-beta456",
                    "title": "Batch beta task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                },
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "summitflow",
                "active_checkpoints": 2,
                "dirty_checkpoints": 2,
                "needs_cleanup": True,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("summitflow")

    assert [task["id"] for task in payload["running_tasks"]] == ["task-alpha123", "task-beta456"]
    assert payload["stranded_tasks"] == []
    assert payload["summary"]["running_tasks"] == 2
    assert payload["summary"]["stranded_tasks"] == 0


@pytest.mark.asyncio
async def test_build_project_pulse_stale_session_does_not_prevent_stranded() -> None:
    """A stale (non-active) session linked to a task does not protect it from stranded classification."""
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    very_stale = (datetime.now(UTC) - timedelta(hours=7)).isoformat().replace("+00:00", "Z")

    ownership_payload = {"active_owners": [], "active_specialists": []}
    sessions_payload = {
        "sessions": [
            {
                "id": "sess-dead",
                "status": "active",
                "session_type": "claude_code",
                "external_id": "task-dead-abc",
                "updated_at": very_stale,
                "live_activity": {"lifecycle_state": "reapable", "health": "stalled", "reapable": True},
            }
        ]
    }

    with (
        patch(
            "app.services.project_pulse._agent_hub_get",
            new=AsyncMock(side_effect=[ownership_payload, sessions_payload]),
        ),
        patch(
            "app.services.project_pulse.list_tasks",
            return_value=[
                {
                    "id": "task-dead-abc",
                    "title": "Dead lane task",
                    "status": "running",
                    "task_type": "task",
                    "priority": 2,
                    "updated_at": stale,
                }
            ],
        ),
        patch(
            "app.services.project_pulse.build_project_cleanup_status",
            return_value={
                "project_id": "summitflow",
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
        ),
    ):
        from app.services.project_pulse import build_project_pulse

        payload = await build_project_pulse("summitflow")

    assert payload["running_tasks"] == []
    assert [task["id"] for task in payload["stranded_tasks"]] == ["task-dead-abc"]
    assert payload["summary"]["running_tasks"] == 0
    assert payload["summary"]["stranded_tasks"] == 1
