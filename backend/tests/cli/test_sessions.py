"""Tests for st sessions CLI commands."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

try:
    from cli.main import app
except ImportError as e:
    pytest.skip(f"Cannot import cli.main (missing dependency: {e})", allow_module_level=True)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_observability_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setattr(sessions_cmd, "refresh_agent_observability", lambda: None)


class TestSessionClientContract:
    """Tests for low-level session list response normalization."""

    def test_list_sessions_accepts_paginated_response_object(self) -> None:
        from cli import _client_execution as exec_ops

        mock_http = MagicMock()
        mock_http.get.return_value = MagicMock()

        result = exec_ops.list_sessions(
            mock_http,
            lambda path: f"http://test{path}",
            lambda _response: {"sessions": [{"id": "sess-1"}]},
        )

        assert result == [{"id": "sess-1"}]

    def test_list_sessions_accepts_legacy_list_response(self) -> None:
        from cli import _client_execution as exec_ops

        mock_http = MagicMock()
        mock_http.get.return_value = MagicMock()

        result = exec_ops.list_sessions(
            mock_http,
            lambda path: f"http://test{path}",
            lambda _response: [{"id": "sess-2"}],
        )

        assert result == [{"id": "sess-2"}]

    def test_execution_mixin_uses_agent_hub_sessions_proxy(self) -> None:
        from cli._client_mixins_execution import ExecutionOperationsMixin

        class _Dummy(ExecutionOperationsMixin):
            def __init__(self) -> None:
                self._client = MagicMock()
                self._handle_response = lambda response: response

            @staticmethod
            def _global_url(path: str) -> str:
                return f"http://test{path}"

        dummy = _Dummy()

        with patch("cli._client_mixins_execution.exec_ops.list_sessions", return_value=[]) as mock_list:
            dummy.list_sessions(status="active", limit=5, parent_session_id="parent-1")

        assert mock_list.call_args.args[1]("/sessions") == "http://test/agent-hub/sessions"

    def test_execution_mixin_uses_agent_hub_session_detail_proxy(self) -> None:
        from cli._client_mixins_execution import ExecutionOperationsMixin

        class _Dummy(ExecutionOperationsMixin):
            def __init__(self) -> None:
                self._client = MagicMock()
                self._handle_response = lambda response: response

            @staticmethod
            def _global_url(path: str) -> str:
                return f"http://test{path}"

        dummy = _Dummy()

        with patch("cli._client_mixins_execution.exec_ops.get_session", return_value={}) as mock_get:
            dummy.get_session("sess-123")

        assert mock_get.call_args.args[1]("/sessions/sess-123") == "http://test/agent-hub/sessions/sess-123"


class TestSessionsListCommand:
    """Tests for `st sessions list`."""

    def test_list_unwraps_session_list_response(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [
            {
                "id": "sess-1",
                "agent_slug": "debugger",
                "status": "completed",
                "summary_oneliner": "Recovered stale state.",
            }
        ]

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions", "list"])

        assert result.exit_code == 0
        assert "sess-1" in result.output
        mock_client.list_sessions.assert_called_once_with(
            status=None,
            limit=20,
            page=1,
            agent_slug=None,
            parent_session_id=None,
            project_id=None,
        )

    def test_list_passes_filters_to_client(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(
                app,
                [
                    "sessions",
                    "list",
                    "--status",
                    "completed",
                    "--limit",
                    "5",
                    "--agent",
                    "debugger",
                    "--parent-session",
                    "parent-123",
                    "--project",
                    "summitflow",
                ],
            )

        assert result.exit_code == 0
        mock_client.list_sessions.assert_called_once_with(
            status="completed",
            limit=5,
            page=1,
            agent_slug="debugger",
            parent_session_id="parent-123",
            project_id="summitflow",
        )

    def test_list_normalizes_running_status_to_active(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions", "list", "--status", "running"])

        assert result.exit_code == 0
        mock_client.list_sessions.assert_called_once_with(
            status="active",
            limit=20,
            page=1,
            agent_slug=None,
            parent_session_id=None,
            project_id=None,
        )

    def test_list_refreshes_observability_before_querying(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []

        with (
            patch("cli.commands.sessions.refresh_agent_observability") as mock_refresh,
            patch("cli.commands.sessions.STClient", return_value=mock_client),
        ):
            result = runner.invoke(app, ["sessions", "list", "--status", "active"])

        assert result.exit_code == 0
        mock_refresh.assert_called_once_with()


class TestSessionsCommandAliases:
    """Tests for root-level `st sessions` aliases."""

    def test_sessions_root_aliases_to_list(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [
            {"id": "sess-root", "status": "running", "agent_slug": "debugger"}
        ]

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions"])

        assert result.exit_code == 0
        assert "sess-root" in result.output
        mock_client.list_sessions.assert_called_once_with(
            status=None,
            limit=20,
            page=1,
            agent_slug=None,
            parent_session_id=None,
            project_id=None,
        )

    def test_sessions_root_forwards_list_filters(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions", "--status", "running", "--limit", "7"])

        assert result.exit_code == 0
        mock_client.list_sessions.assert_called_once_with(
            status="active",
            limit=7,
            page=1,
            agent_slug=None,
            parent_session_id=None,
            project_id=None,
        )


class TestSessionCommands:
    """Tests for helper behavior in session listing."""

    def test_list_command_hides_unassigned_sessions_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.commands import sessions as sessions_cmd

        captured: dict[str, object] = {}

        class _DummyClient:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def list_sessions(self, **_: object) -> list[dict[str, object]]:
                return [
                    {"id": "sess-1", "status": "completed", "agent_slug": "coder"},
                    {"id": "sess-2", "status": "active", "agent_slug": None},
                ]

        monkeypatch.setattr(sessions_cmd, "STClient", _DummyClient)
        monkeypatch.setattr(
            sessions_cmd,
            "output_json",
            lambda payload: captured.setdefault("payload", payload),
        )

        sessions_cmd.list_sessions(limit=10)

        assert captured["payload"] == [
            {"id": "sess-1", "status": "completed", "agent_slug": "coder"}
        ]

    def test_list_command_can_include_unassigned_sessions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.commands import sessions as sessions_cmd

        captured: dict[str, object] = {}

        class _DummyClient:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def list_sessions(self, **_: object) -> list[dict[str, object]]:
                return [
                    {"id": "sess-1", "status": "completed", "agent_slug": "coder"},
                    {"id": "sess-2", "status": "active", "agent_slug": None},
                ]

        monkeypatch.setattr(sessions_cmd, "STClient", _DummyClient)
        monkeypatch.setattr(
            sessions_cmd,
            "output_json",
            lambda payload: captured.setdefault("payload", payload),
        )

        sessions_cmd.list_sessions(limit=10, include_unassigned=True)

        assert captured["payload"] == [
            {"id": "sess-1", "status": "completed", "agent_slug": "coder"},
            {"id": "sess-2", "status": "active", "agent_slug": None},
        ]

    def test_reap_dry_run_only_outputs_reapable_sessions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.commands import sessions as sessions_cmd

        captured: dict[str, object] = {}

        class _DummyClient:
            project_id = "agent-hub"

            def __init__(self, require_project: bool = False) -> None:
                self.require_project = require_project

            def list_sessions(self, **kwargs: object) -> list[dict[str, object]]:
                assert kwargs["status"] == "active"
                return [
                    {
                        "id": "sess-1",
                        "project_id": "agent-hub",
                        "agent_slug": "debugger",
                        "session_type": "agent",
                        "live_activity": {
                            "lifecycle_state": "reapable",
                            "reapable": True,
                            "reapable_reason": "heartbeat_only+no_lane",
                        },
                    },
                    {
                        "id": "sess-2",
                        "project_id": "agent-hub",
                        "agent_slug": "debugger",
                        "session_type": "agent",
                        "live_activity": {"lifecycle_state": "stalled", "reapable": False},
                    },
                ]

        monkeypatch.setattr(sessions_cmd, "STClient", _DummyClient)
        monkeypatch.setattr(
            sessions_cmd,
            "output_json",
            lambda payload: captured.setdefault("payload", payload),
        )

        sessions_cmd.reap_sessions(dry_run=True)

        assert captured["payload"] == {
            "project_id": "agent-hub",
            "dry_run": True,
            "reapable_count": 1,
            "reapable_sessions": [
                {
                    "id": "sess-1",
                    "project_id": "agent-hub",
                    "agent_slug": "debugger",
                    "session_type": "agent",
                    "reapable_reason": "heartbeat_only+no_lane",
                }
            ],
        }

    def test_reap_closes_each_reapable_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.commands import sessions as sessions_cmd

        captured: dict[str, object] = {}

        class _DummyClient:
            project_id = "agent-hub"

            def __init__(self, require_project: bool = False) -> None:
                self.require_project = require_project

            def list_sessions(self, **kwargs: object) -> list[dict[str, object]]:
                assert kwargs["page"] == 1
                return [
                    {
                        "id": "sess-1",
                        "project_id": "agent-hub",
                        "live_activity": {"lifecycle_state": "reapable", "reapable": True},
                    }
                ]

            def close_session(self, session_id: str) -> dict[str, object]:
                return {"id": session_id, "status": "completed"}

        monkeypatch.setattr(sessions_cmd, "STClient", _DummyClient)
        monkeypatch.setattr(
            sessions_cmd,
            "output_json",
            lambda payload: captured.setdefault("payload", payload),
        )

        sessions_cmd.reap_sessions(dry_run=False)

        assert captured["payload"] == {
            "project_id": "agent-hub",
            "dry_run": False,
            "reapable_count": 1,
            "closed_count": 1,
            "closed_sessions": [{"id": "sess-1", "status": "completed"}],
            "failed_count": 0,
            "failed_sessions": [],
        }

    def test_list_all_active_sessions_paginates_multiple_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.commands import sessions as sessions_cmd

        class _DummyClient:
            def list_sessions(self, **kwargs: object) -> list[dict[str, object]]:
                page = cast(int, kwargs.get("page", 1))
                limit = cast(int, kwargs.get("limit", 100))
                # Return different sessions for each page
                if page == 1:
                    return [
                        {"id": f"sess-{i}", "project_id": "agent-hub"}
                        for i in range(1, limit + 1)
                    ]
                elif page == 2:
                    return [
                        {"id": f"sess-{i}", "project_id": "agent-hub"}
                        for i in range(limit + 1, limit + 51)
                    ]
                else:
                    return []

        monkeypatch.setattr(sessions_cmd, "STClient", _DummyClient)

        client = _DummyClient()
        result = sessions_cmd._list_all_active_sessions(
            cast(Any, client), project_id="agent-hub", page_size=100
        )

        # Should combine sessions from both pages (100 from page 1 + 50 from page 2)
        assert len(result) == 150
        assert result[0]["id"] == "sess-1"
        assert result[99]["id"] == "sess-100"
        assert result[100]["id"] == "sess-101"
        assert result[149]["id"] == "sess-150"


class TestRequireProjectFalse:
    """Regression tests: sessions commands work from a non-project cwd."""

    def test_list_sessions_constructs_client_without_project_required(self) -> None:
        captured_kwargs: list[dict[str, object]] = []

        class _DummyClient:
            def __init__(self, **kwargs: object) -> None:
                captured_kwargs.append(kwargs)

            def list_sessions(self, **_: object) -> list[dict[str, object]]:
                return []

        with patch("cli.commands.sessions.STClient", side_effect=_DummyClient):
            result = runner.invoke(app, ["sessions", "list", "-s", "active", "--include-unassigned"])

        assert result.exit_code == 0
        assert captured_kwargs == [{"require_project": False}]

    def test_show_session_constructs_client_without_project_required(self) -> None:
        captured_kwargs: list[dict[str, object]] = []

        class _DummyClient:
            def __init__(self, **kwargs: object) -> None:
                captured_kwargs.append(kwargs)

            def get_session(self, session_id: str) -> dict[str, object]:
                return {"id": session_id, "status": "completed"}

        with patch("cli.commands.sessions.STClient", side_effect=_DummyClient):
            result = runner.invoke(app, ["sessions", "show", "sess-abc"])

        assert result.exit_code == 0
        assert captured_kwargs == [{"require_project": False}]

    def test_close_session_constructs_client_without_project_required(self) -> None:
        captured_kwargs: list[dict[str, object]] = []

        class _DummyClient:
            def __init__(self, **kwargs: object) -> None:
                captured_kwargs.append(kwargs)

            def close_session(self, session_id: str) -> dict[str, object]:
                return {"id": session_id, "status": "completed"}

        with patch("cli.commands.sessions.STClient", side_effect=_DummyClient):
            result = runner.invoke(app, ["sessions", "close", "sess-xyz"])

        assert result.exit_code == 0
        assert captured_kwargs == [{"require_project": False}]

    def test_list_sessions_project_flag_forwarded_to_api(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(
                app, ["sessions", "list", "-s", "active", "--project", "summitflow"]
            )

        assert result.exit_code == 0
        mock_client.list_sessions.assert_called_once_with(
            status="active",
            limit=20,
            page=1,
            agent_slug=None,
            parent_session_id=None,
            project_id="summitflow",
        )

    def test_list_sessions_in_project_cwd_still_works(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [
            {"id": "sess-in-project", "agent_slug": "coder", "status": "active"}
        ]

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions", "list", "-s", "active"])

        assert result.exit_code == 0
        assert "sess-in-project" in result.output
        mock_client.list_sessions.assert_called_once_with(
            status="active",
            limit=20,
            page=1,
            agent_slug=None,
            parent_session_id=None,
            project_id=None,
        )


class TestOwnershipCommand:
    """Tests for `st sessions ownership`."""

    def test_ownership_lists_cross_project_rows_in_compact_mode(self) -> None:
        mock_client = MagicMock()
        mock_client.get.side_effect = [
            [{"id": "summitflow"}, {"id": "agent-hub"}],
            {
                "active_owners": [
                    {
                        "task_id": "task-1",
                        "session_id": "sess-1",
                        "agent_slug": "coder",
                        "ownership_kind": "scoped",
                        "branch": "task-1/main",
                        "worktree_path": "/tmp/task-1",
                        "scope_paths": ["backend/app/foo.py"],
                        "is_stale": False,
                    }
                ]
            },
            {"active_owners": []},
        ]

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions", "ownership"])

        assert result.exit_code == 0
        assert "OWNERSHIP[1]" in result.output
        assert "OWN summitflow | task-1 | coder | sess-1 | kind=scoped" in result.output
        assert "branch=task-1/main" in result.output
        assert "cwd=/tmp/task-1" in result.output
        assert "paths=backend/app/foo.py" in result.output

        assert mock_client.get.call_count == 3
        global_url_paths = [call.args[0] for call in mock_client._global_url.call_args_list]
        assert global_url_paths == [
            "/projects",
            "/agent-hub/ownership/projects/summitflow/live",
            "/agent-hub/ownership/projects/agent-hub/live",
        ]

    def test_ownership_outputs_json_when_not_compact(self) -> None:
        mock_client = MagicMock()
        mock_client.get.side_effect = [
            {
                "active_owners": [
                    {
                        "task_id": "task-2",
                        "session_id": "sess-2",
                        "agent_slug": "reviewer",
                        "ownership_kind": "unscoped",
                    }
                ]
            }
        ]

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["--no-compact", "sessions", "ownership", "--project", "agent-hub"])

        assert result.exit_code == 0
        assert '"total": 1' in result.output
        assert '"project_id": "agent-hub"' in result.output
        assert '"task_id": "task-2"' in result.output


class TestOverlapCommand:
    """Tests for `st sessions overlap`."""

    def test_overlap_lists_exact_write_and_read_overlap_rows(self) -> None:
        mock_client = MagicMock()
        mock_client.get.side_effect = [
            {
                "active_owners": [
                    {
                        "task_id": "task-1",
                        "session_id": "sess-1",
                        "declared_scope_paths": ["backend/app/foo.py"],
                        "observed_read_paths": [],
                        "observed_write_paths": ["backend/app/foo.py"],
                    },
                    {
                        "task_id": "task-2",
                        "session_id": "sess-2",
                        "declared_scope_paths": ["backend/app/foo.py"],
                        "observed_read_paths": ["backend/app/bar.py"],
                        "observed_write_paths": ["backend/app/foo.py"],
                    },
                    {
                        "task_id": "task-3",
                        "session_id": "sess-3",
                        "declared_scope_paths": ["backend/app/bar.py"],
                        "observed_read_paths": [],
                        "observed_write_paths": ["backend/app/bar.py"],
                    },
                ]
            }
        ]

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions", "overlap", "--project", "summitflow"])

        assert result.exit_code == 0
        assert "OVERLAPS[2]" in result.output
        assert "OVR summitflow | block | exact_write | task-1 | task-2 | paths=backend/app/foo.py" in result.output
        assert "OVR summitflow | warn | read_overlap | task-2 | task-3 | paths=backend/app/bar.py" in result.output
