"""Tests for `st pulse` coordination output."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.lib.jj import JJRepoStatus
from cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_observability_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands import pulse as pulse_cmd

    monkeypatch.setattr(pulse_cmd, "refresh_agent_observability", lambda: None)
    monkeypatch.setattr(pulse_cmd, "_jj_status_for_project", lambda _project_id: None)


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
        result = runner.invoke(app, ["pulse", "--project", "agent-hub", "--details"])

    assert result.exit_code == 0
    assert "PULSE:agent-hub|tasks=1|writers=1|readers=0|specialists=0|sessions=2|stale=1|reapable=1|checkpoints=1|dirty=0|cleanup=no|stranded=0" in result.output
    assert "PREFLIGHT:agent-hub|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output
    assert "RUN task-1 | running | P2 | Refactor timeline" in result.output
    assert "WRITE task-1 | refactor | sess-own | kind=scoped | paths=frontend/src/app.tsx" in result.output
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
        result = runner.invoke(app, ["pulse", "--project", "agent-hub", "--details"])

    assert result.exit_code == 0
    assert "WRITE task-2 | refactor | sess-own | kind=task_checkout" in result.output


def test_pulse_compact_fetches_compact_api_payload_by_default() -> None:
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
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert mock_client.get.call_args.args[0].endswith("/projects/agent-hub/pulse?compact=true")


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
        result = runner.invoke(app, ["pulse", "--project", "agent-hub", "--details"])

    assert result.exit_code == 0
    assert "PULSE:agent-hub|tasks=0|writers=0|readers=0|specialists=0|sessions=0|stale=1|reapable=1|checkpoints=1|dirty=1|cleanup=yes|stranded=1" in result.output
    assert "REVIEW:agent-hub|ownerless=yes|dirty=1|checkpoints=1|stranded=1|" in result.output
    assert "STRANDED task-3 | running | no_owner_session | Refactor tool handlers" in result.output


def test_pulse_compact_reports_jj_state_without_checkpoint_preflight_block() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "monkey-fight",
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
            "active_checkpoints": 1,
            "dirty_checkpoints": 0,
            "needs_cleanup": True,
        },
        "running_tasks": [],
        "active_owners": [],
        "active_sessions": [],
        "stale_sessions": [],
        "stranded_tasks": [],
    }
    jj_status = JJRepoStatus(
        repo="monkey-fight",
        path="/srv/workspaces/projects/monkey-fight",
        branch="main",
        colocated=True,
        state="described",
        described=True,
        conflicted=False,
        unpublished=1,
        change_id="chg",
        commit_id="commit",
    )

    with (
        patch("cli.commands.pulse.STClient", return_value=mock_client),
        patch("cli.commands.pulse._jj_status_for_project", return_value=jj_status),
    ):
        result = runner.invoke(app, ["pulse", "--project", "monkey-fight"])

    assert result.exit_code == 0
    assert "JJSTATE:monkey-fight|state=described|described=true|conflicts=false|unpublished=1|change=chg|commit=commit" in result.output
    assert "PREFLIGHT:monkey-fight|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output


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
    assert "PULSE:test2|tasks=0|writers=0|readers=0|specialists=0|sessions=0|stale=0|reapable=0|checkpoints=0|dirty=1|cleanup=yes|stranded=0" in result.output
    assert "PREFLIGHT:test2|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output
    assert "REVIEW:test2|ownerless=yes|dirty=1|checkpoints=0|stranded=0|" in result.output


def test_pulse_compact_requires_review_for_ownerless_clean_checkpoint() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "portfolio-ai",
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
            "active_checkpoints": 1,
            "dirty_checkpoints": 0,
            "dirty_main_repo": False,
            "needs_cleanup": True,
        },
        "running_tasks": [],
        "active_owners": [],
        "active_sessions": [],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "portfolio-ai"])

    assert result.exit_code == 0
    assert "PREFLIGHT:portfolio-ai|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output
    assert "REVIEW:portfolio-ai|ownerless=yes|dirty=0|checkpoints=1|stranded=0|" in result.output
    assert "ownership=diagnostic-only" in result.output
    assert "commit-push-prune-or-leave-explicit-handoff" in result.output


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
        result = runner.invoke(app, ["pulse", "--project", "agent-hub", "--details"])

    assert result.exit_code == 0
    assert "SES observer | summitflow/codex-session-sync | sess-obs | gpt-5.4 | quiet/waiting_for_model" in result.output


def test_pulse_compact_renders_readers_as_nonblocking() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "agent-hub",
        "summary": {
            "running_tasks": 0,
            "active_owners": 0,
            "active_readers": 1,
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
        "active_readers": [
            {
                "session_id": "sess-reader",
                "agent_slug": None,
                "observed_read_paths": ["backend/app/api/tasks.py"],
                "scope_confidence": "observed_read",
            }
        ],
        "active_sessions": [{"id": "sess-reader"}],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "agent-hub", "--gate"])
        details_result = runner.invoke(app, ["pulse", "--project", "agent-hub", "--gate", "--details"])

    assert result.exit_code == 0
    assert "PULSE:agent-hub|tasks=0|writers=0|readers=1|" in result.output
    assert "PREFLIGHT:agent-hub|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output
    assert "READ " not in result.output
    assert "SES observer" not in result.output
    assert details_result.exit_code == 0
    assert "READ - | ? | sess-rea | paths=backend/app/api/tasks.py | scope=observed_read" in details_result.output
    assert "SES observer" not in details_result.output


def test_pulse_all_shows_cross_project_overview() -> None:
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
        result = runner.invoke(app, ["pulse", "--all"])

    assert result.exit_code == 0
    assert "PULSE:summitflow|tasks=0|writers=0|readers=0|specialists=0|sessions=1|stale=2|reapable=1|checkpoints=0|dirty=0|cleanup=no|stranded=0" in result.output
    assert "PREFLIGHT:summitflow|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output
    assert "PULSE:agent-hub|tasks=1|writers=1|readers=0|specialists=0|sessions=2|stale=0|reapable=0|checkpoints=0|dirty=0|cleanup=no|stranded=0" in result.output
    assert "PREFLIGHT:agent-hub|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output


def test_pulse_defaults_to_detected_current_project() -> None:
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
        patch("cli.commands.pulse.STClient", return_value=mock_client),
        patch("cli.commands.pulse.get_config_optional", return_value=MagicMock(project_id="agent-hub")),
    ):
        result = runner.invoke(app, ["pulse"])

    assert result.exit_code == 0
    mock_client.get.assert_called_once()
    assert "PULSE:agent-hub|" in result.output


def test_pulse_gate_requires_current_project_or_explicit_all() -> None:
    mock_client = MagicMock()

    with (
        patch("cli.commands.pulse.STClient", return_value=mock_client),
        patch("cli.commands.pulse.get_config_optional", return_value=MagicMock(project_id="")),
    ):
        result = runner.invoke(app, ["pulse", "--gate"])

    assert result.exit_code == 2
    assert "Pulse gate requires a current project." in result.output
    mock_client.get.assert_not_called()


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


def test_pulse_compact_surfaces_clear_lane_preflight() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "sha",
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
            "dirty_main_repo": False,
            "needs_cleanup": False,
        },
        "running_tasks": [],
        "active_owners": [],
        "active_sessions": [],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "sha"])

    assert result.exit_code == 0
    assert "PREFLIGHT:sha|claim=clear|edit=clear|reasons=-|source=st-pulse" in result.output


def test_pulse_gate_ignores_checkpoint_residue() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = {
        "project_id": "summitflow",
        "summary": {
            "running_tasks": 0,
            "active_owners": 1,
            "active_specialists": 0,
            "active_sessions": 1,
            "stale_sessions": 0,
            "reapable_sessions": 0,
            "stranded_tasks": 0,
        },
        "cleanup": {"active_checkpoints": 1, "dirty_checkpoints": 0, "needs_cleanup": True},
        "running_tasks": [],
        "active_owners": [{"task_id": "task-2", "session_id": "sess-2"}],
        "active_sessions": [{"id": "sess-2"}],
        "stale_sessions": [],
        "stranded_tasks": [],
    }

    with patch("cli.commands.pulse.STClient", return_value=mock_client):
        result = runner.invoke(app, ["pulse", "--project", "summitflow", "--gate"])

    assert result.exit_code == 0
    assert "PREFLIGHT:summitflow|claim=clear|edit=clear|reasons=-" in result.output


def test_require_pulse_gate_allows_current_task_owner() -> None:
    from cli.commands import pulse

    payload = {
        "project_id": "summitflow",
        "summary": {
            "running_tasks": 1,
            "active_owners": 1,
            "active_specialists": 0,
            "active_sessions": 1,
            "stranded_tasks": 0,
        },
        "cleanup": {"active_checkpoints": 0, "dirty_checkpoints": 0, "needs_cleanup": False},
        "running_tasks": [{"id": "task-1"}],
        "active_owners": [{"task_id": "task-1", "session_id": "sess-1"}],
        "active_specialists": [],
        "active_sessions": [{"id": "sess-1"}],
        "stranded_tasks": [],
    }

    with patch.object(pulse, "fetch_pulse_payload", return_value=payload):
        pulse.require_pulse_gate("summitflow", allow_task_id="task-1")


def test_require_pulse_gate_allows_current_task_checkpoint() -> None:
    from cli.commands import pulse

    payload = {
        "project_id": "summitflow",
        "summary": {
            "running_tasks": 0,
            "active_owners": 0,
            "active_specialists": 0,
            "active_sessions": 0,
            "stranded_tasks": 0,
        },
        "cleanup": {
            "active_checkpoints": 1,
            "dirty_checkpoints": 0,
            "needs_cleanup": True,
            "checkpoint_task_ids": ["task-1"],
        },
        "running_tasks": [],
        "active_owners": [],
        "active_specialists": [],
        "active_sessions": [],
        "stranded_tasks": [],
    }

    with patch.object(pulse, "fetch_pulse_payload", return_value=payload):
        pulse.require_pulse_gate("summitflow", allow_task_id="task-1")


def test_claim_task_runs_pulse_gate_before_checkpoint_creation() -> None:
    from cli.commands import claim

    client = MagicMock()
    client.get_task.return_value = {"id": "task-1", "status": "pending", "project_id": "summitflow"}
    with (
        patch.object(claim, "get_snapshot_info", return_value=None),
        patch.object(claim, "require_pulse_gate") as mock_gate,
        patch.object(claim, "_require_task_lane_clear") as mock_lane,
        patch.object(claim, "require_claim_safe_tree") as mock_safe,
        patch.object(claim, "create_task_snapshot") as mock_snapshot,
    ):
        mock_snapshot.return_value = MagicMock(base_branch="main")
        result = claim._claim_task(client, "task-1")

    mock_gate.assert_called_once_with("summitflow")
    mock_lane.assert_called_once_with("task-1", "summitflow")
    mock_safe.assert_called_once()
    assert result["action"] == "claimed"


def test_done_task_runs_pulse_gate_before_completion() -> None:
    from cli.commands import done

    events: list[str] = []
    client = MagicMock()
    client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}

    with (
        patch.object(done, "require_pulse_gate", side_effect=lambda *_args, **_kwargs: events.append("gate")) as mock_gate,
        patch.object(
            done,
            "complete_task",
            side_effect=lambda *_args, **_kwargs: events.append("complete")
            or {"project_id": "summitflow", "merged": False},
        ) as mock_complete,
    ):
        done._handle_task_completion(client, "task-1", None, strict=False, admin=False)

    assert events == ["gate", "complete", "gate"]
    assert mock_gate.call_args_list[0].args == ("summitflow",)
    assert mock_gate.call_args_list[0].kwargs == {"allow_task_id": "task-1"}
    mock_complete.assert_called_once()
