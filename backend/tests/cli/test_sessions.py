"""Tests for st sessions CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

try:
    from cli.main import app
except ImportError as e:
    pytest.skip(f"Cannot import cli.main (missing dependency: {e})", allow_module_level=True)

runner = CliRunner()


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
                ],
            )

        assert result.exit_code == 0
        mock_client.list_sessions.assert_called_once_with(
            status="completed",
            limit=5,
            page=1,
            agent_slug="debugger",
            parent_session_id="parent-123",
        )


class TestSessionsCommandAliases:
    """Tests for root-level `st sessions` aliases."""

    def test_sessions_root_aliases_to_list(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [{"id": "sess-root", "status": "running"}]

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
        )

    def test_sessions_root_forwards_list_filters(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = []

        with patch("cli.commands.sessions.STClient", return_value=mock_client):
            result = runner.invoke(app, ["sessions", "--status", "running", "--limit", "7"])

        assert result.exit_code == 0
        mock_client.list_sessions.assert_called_once_with(
            status="running",
            limit=7,
            page=1,
            agent_slug=None,
            parent_session_id=None,
        )
