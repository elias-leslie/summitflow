"""Tests for `st pulse` coordination output."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_observability_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands import pulse as pulse_cmd

    monkeypatch.setattr(pulse_cmd, "refresh_agent_observability", lambda: None)


def test_pulse_compact_renders_canonical_summary() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 1,
            "active_owners": 1,
            "active_specialists": 0,
            "active_sessions": 2,
            "stale_sessions": 1,
            "reapable_sessions": 1,
            "stranded_tasks": 0,
        },
        "cleanup": {
            "active_checkpoints": 1,
            "dirty_checkpoints": 0,
            "needs_cleanup": False,
        },
        "running_tasks": [
            {"id": "task-1", "status": "running", "priority": 2, "title": "Refactor timeline"}
        ],
        "active_owners": [
            {
                "task_id": "task-1",
                "agent_slug": "refactor",
                "session_id": "sess-owner",
                "ownership_kind": "scoped",
                "scope_paths": ["frontend/src/app.tsx"],
            }
        ],
        "active_sessions": [
            {
                "id": "sess-owner",
                "lane_role": "owner",
                "agent_slug": "refactor",
                "effective_model": "claude-sonnet-4-6",
                "status": "active",
                "live_activity": {"health": "active", "phase": "reading_file", "files_touched": []},
            }
        ],
        "stale_sessions": [
            {
                "id": "sess-stale",
                "lane_role": "observer",
                "session_type": "agent",
                "request_source": "codex-transcript-sync",
                "source_client": "summitflow/codex-session-sync",
                "effective_model": "claude-sonnet-4-6",
                "status": "active",
                "live_activity": {
                    "health": "stalled",
                    "phase": "waiting_for_model",
                    "lifecycle_state": "reapable",
                    "reapable_reason": "heartbeat_only+no_lane",
                },
            }
        ],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "PULSE:agent-hub|tasks=1|owners=1|specialists=0|sessions=2|stale=1|reapable=1|checkpoints=1|dirty=0|cleanup=no|stranded=0" in result.output
    assert "RUN task-1 | running | P2 | Refactor timeline" in result.output
    assert "OWN task-1 | refactor | sess-own | kind=scoped | paths=frontend/src/app.tsx" in result.output
    assert "SES owner | refactor | sess-own | claude-sonnet-4-6 | active/reading_file" in result.output
    assert "STALE observer | summitflow/codex-session-sync | sess-sta | claude-sonnet-4-6 | reapable | reason=heartbeat_only+no_lane" in result.output


def test_pulse_compact_labels_task_checkout_owner_more_usefully() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 1,
            "active_owners": 1,
            "active_specialists": 0,
            "active_sessions": 1,
            "stale_sessions": 0,
            "reapable_sessions": 0,
            "stranded_tasks": 0,
        },
        "cleanup": {
            "active_checkpoints": 1,
            "dirty_checkpoints": 0,
            "needs_cleanup": False,
        },
        "running_tasks": [
            {"id": "task-2", "status": "running", "priority": 3, "title": "Refactor image endpoint"}
        ],
        "active_owners": [
            {
                "task_id": "task-2",
                "agent_slug": "refactor",
                "session_id": "sess-owner",
                "ownership_kind": "unscoped",
                "scope_paths": [],
            }
        ],
        "active_sessions": [],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "OWN task-2 | refactor | sess-own | kind=task_checkout" in result.output


def test_pulse_compact_surfaces_stranded_running_tasks() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 0,
            "active_owners": 0,
            "active_specialists": 0,
            "active_sessions": 0,
            "stale_sessions": 1,
            "reapable_sessions": 1,
            "stranded_tasks": 1,
        },
        "cleanup": {
            "active_checkpoints": 1,
            "dirty_checkpoints": 1,
            "needs_cleanup": True,
        },
        "running_tasks": [],
        "active_owners": [],
        "active_sessions": [],
        "stale_sessions": [
            {
                "id": "sess-stale",
                "lane_role": "observer",
                "session_type": "agent",
                "request_source": "codex-transcript-sync",
                "source_client": "summitflow/codex-session-sync",
                "effective_model": "claude-sonnet-4-6",
                "status": "active",
                "live_activity": {"lifecycle_state": "reapable", "reapable_reason": "heartbeat_only+no_lane"},
            }
        ],
        "stranded_tasks": [
            {"id": "task-3", "status": "running", "priority": 2, "title": "Refactor tool handlers"}
        ],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "PULSE:agent-hub|tasks=0|owners=0|specialists=0|sessions=0|stale=1|reapable=1|checkpoints=1|dirty=1|cleanup=yes|stranded=1" in result.output
    assert "STRANDED task-3 | running | no_owner_session | Refactor tool handlers" in result.output


def test_pulse_compact_counts_dirty_main_repo_without_checkpoints() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "test2",
        "summary": {
            "running_tasks": 0,
            "active_owners": 0,
            "active_specialists": 0,
            "active_sessions": 0,
            "stale_sessions": 0,
            "reapable_sessions": 0,
            "stranded_tasks": 0,
        },
        "cleanup": {
            "active_checkpoints": 0,
            "dirty_checkpoints": 1,
            "dirty_main_repo": True,
            "needs_cleanup": True,
        },
        "running_tasks": [],
        "active_owners": [],
        "active_sessions": [],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "test2"])

    assert result.exit_code == 0
    assert "PULSE:test2|tasks=0|owners=0|specialists=0|sessions=0|stale=0|reapable=0|checkpoints=0|dirty=1|cleanup=yes|stranded=0" in result.output


def test_pulse_prefers_source_client_for_observer_session_label() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 0,
            "active_owners": 0,
            "active_specialists": 0,
            "active_sessions": 1,
            "stale_sessions": 0,
            "reapable_sessions": 0,
            "stranded_tasks": 0,
        },
        "cleanup": {
            "active_checkpoints": 0,
            "dirty_checkpoints": 0,
            "needs_cleanup": False,
        },
        "running_tasks": [],
        "active_owners": [],
        "active_sessions": [
            {
                "id": "sess-observer",
                "lane_role": "observer",
                "session_type": "agent",
                "request_source": "codex-transcript-sync",
                "source_client": "summitflow/codex-session-sync",
                "effective_model": "codex/gpt-5.4",
                "status": "active",
                "live_activity": {"health": "quiet", "phase": "waiting_for_model", "files_touched": []},
            }
        ],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "SES observer | summitflow/codex-session-sync | sess-obs | gpt-5.4 | quiet/waiting_for_model" in result.output


def test_pulse_defaults_to_cross_project_overview() -> None:
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        [{"id": "summitflow"}, {"id": "agent-hub"}],
        {
            "project_id": "summitflow",
            "summary": {
                "running_tasks": 0,
                "active_owners": 0,
                "active_specialists": 0,
                "active_sessions": 1,
                "stale_sessions": 2,
                "reapable_sessions": 1,
                "stranded_tasks": 0,
            },
            "cleanup": {
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
            "running_tasks": [],
            "active_owners": [],
            "active_sessions": [],
            "stale_sessions": [],
            "stranded_tasks": [],
        },
        {
            "project_id": "agent-hub",
            "summary": {
                "running_tasks": 1,
                "active_owners": 1,
                "active_specialists": 0,
                "active_sessions": 2,
                "stale_sessions": 0,
                "reapable_sessions": 0,
                "stranded_tasks": 0,
            },
            "cleanup": {
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "needs_cleanup": False,
            },
            "running_tasks": [],
            "active_owners": [],
            "active_sessions": [],
            "stale_sessions": [],
            "stranded_tasks": [],
        },
    ]

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse"])

    assert result.exit_code == 0
    assert "PULSE:summitflow|tasks=0|owners=0|specialists=0|sessions=1|stale=2|reapable=1|checkpoints=0|dirty=0|cleanup=no|stranded=0" in result.output
    assert "PULSE:agent-hub|tasks=1|owners=1|specialists=0|sessions=2|stale=0|reapable=0|checkpoints=0|dirty=0|cleanup=no|stranded=0" in result.output


def test_pulse_rejects_project_and_all_together() -> None:
    result = runner.invoke(app, ["pulse", "--project", "agent-hub", "--all"])

    assert result.exit_code != 0
    assert "Use either --project or --all, not both." in result.output


def test_pulse_refreshes_observability_before_querying() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 0,
            "active_owners": 0,
            "active_specialists": 0,
            "active_sessions": 0,
            "stale_sessions": 0,
            "reapable_sessions": 0,
            "stranded_tasks": 0,
        },
        "cleanup": {
            "active_checkpoints": 0,
            "dirty_checkpoints": 0,
            "needs_cleanup": False,
        },
        "running_tasks": [],
        "active_owners": [],
        "active_sessions": [],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with (
        patch("cli.commands.pulse.refresh_agent_observability") as mock_refresh,
        patch("cli.commands.pulse.STClient", return_value=mock_client),
    ):
        result = runner.invoke(app, ["pulse", "--project", "agent-hub"])

    assert result.exit_code == 0
    mock_refresh.assert_called_once_with()
