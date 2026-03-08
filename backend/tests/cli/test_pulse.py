"""Tests for `st pulse` coordination output."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_pulse_compact_renders_canonical_summary() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 1,
            "active_owners": 1,
            "active_specialists": 0,
            "active_sessions": 2,
        },
        "cleanup": {
            "active_worktrees": 1,
            "dirty_worktrees": 0,
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
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client), patch(
        "cli.commands.pulse.get_config_optional",
        return_value=MagicMock(project_id="agent-hub"),
    ):
        result = runner.invoke(app, ["pulse"])

    assert result.exit_code == 0
    assert "PULSE:agent-hub|tasks=1|owners=1|specialists=0|sessions=2|worktrees=1|dirty=0|cleanup=no" in result.output
    assert "RUN task-1 | running | P2 | Refactor timeline" in result.output
    assert "OWN task-1 | refactor | sess-own | kind=scoped | paths=frontend/src/app.tsx" in result.output
    assert "SES owner | refactor | sess-own | claude-sonnet-4-6 | active/reading_file" in result.output


def test_pulse_compact_labels_task_worktree_owner_more_usefully() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 1,
            "active_owners": 1,
            "active_specialists": 0,
            "active_sessions": 1,
        },
        "cleanup": {
            "active_worktrees": 1,
            "dirty_worktrees": 0,
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
                "is_worktree": True,
            }
        ],
        "active_sessions": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client), patch(
        "cli.commands.pulse.get_config_optional",
        return_value=MagicMock(project_id="agent-hub"),
    ):
        result = runner.invoke(app, ["pulse"])

    assert result.exit_code == 0
    assert "OWN task-2 | refactor | sess-own | kind=task_worktree" in result.output
