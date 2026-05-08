"""Tests for the session-id prefix resolver.

`st sessions list` prints an 8-character short ID, while detail/close/events
endpoints require the full UUID. The resolver bridges the two so operators can
copy the value they see on screen straight into `sessions show`,
`sessions close`, `agent status`, `agent stop`, and `session-events`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

try:
    from cli.commands._session_resolver import resolve_session_id
    from cli.main import app
except ImportError as e:  # pragma: no cover - environment guard
    pytest.skip(f"Cannot import cli.main (missing dependency: {e})", allow_module_level=True)

runner = CliRunner()

_FULL_UUID = "00000000-0000-0000-0000-000000000abc"


class _StubClient:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        self._sessions = sessions
        self.calls: list[dict[str, Any]] = []

    def list_sessions(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        page = int(kwargs.get("page", 1))
        limit = int(kwargs.get("limit", len(self._sessions) or 1))
        start = (page - 1) * limit
        return self._sessions[start:start + limit]


class TestResolveSessionId:
    def test_returns_full_uuid_unchanged(self) -> None:
        client = _StubClient([])
        assert resolve_session_id(_FULL_UUID, client) == _FULL_UUID
        # No prefix lookup performed when the input is already a UUID.
        assert client.calls == []

    def test_resolves_eight_char_prefix_to_full_uuid(self) -> None:
        client = _StubClient([{"id": _FULL_UUID}])
        assert resolve_session_id(_FULL_UUID[:8], client) == _FULL_UUID
        assert client.calls and client.calls[0]["page"] == 1

    def test_ambiguous_prefix_exits_with_clear_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _StubClient(
            [
                {"id": "0000000a-1111-2222-3333-444444444444"},
                {"id": "0000000a-aaaa-bbbb-cccc-dddddddddddd"},
            ]
        )

        with pytest.raises(typer.Exit) as exc:
            resolve_session_id("0000000a", client)

        assert exc.value.exit_code == 1
        err = capsys.readouterr().err
        assert "Ambiguous session ID '0000000a'" in err

    def test_no_match_exits_with_actionable_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _StubClient([{"id": _FULL_UUID}])

        with pytest.raises(typer.Exit) as exc:
            resolve_session_id("deadbeef", client)

        assert exc.value.exit_code == 1
        err = capsys.readouterr().err
        assert "No recent session found" in err and "deadbeef" in err

    def test_prefix_lookup_is_bounded_and_project_scoped(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _StubClient(
            [{"id": f"11111111-1111-1111-1111-{idx:012d}"} for idx in range(100)]
        )

        with pytest.raises(typer.Exit):
            resolve_session_id("deadbeef", client, project_id="summitflow", max_pages=2)

        assert [call["page"] for call in client.calls] == [1, 2]
        assert all(call["project_id"] == "summitflow" for call in client.calls)
        assert "Use the full UUID for older sessions" in capsys.readouterr().err

    def test_empty_session_id_returns_unchanged(self) -> None:
        client = _StubClient([])
        assert resolve_session_id("", client) == ""
        assert client.calls == []


class TestAgentCommandsResolveShortId:
    """`st agent status` and `st agent stop` should accept the short ID."""

    def test_agent_status_resolves_short_id(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [{"id": _FULL_UUID}]
        mock_client.get_session.return_value = {
            "id": _FULL_UUID,
            "status": "active",
            "project_id": "p1",
            "agent_slug": "coder",
            "live_activity": {"status": "ok", "phase": "thinking", "summary": "doing work"},
        }

        with patch("cli.commands.agent.STClient", return_value=mock_client):
            result = runner.invoke(app, ["agent", "status", _FULL_UUID[:8]])

        assert result.exit_code == 0, result.output
        # API was called with the *full* UUID, not the prefix.
        mock_client.get_session.assert_called_once_with(_FULL_UUID)
        assert f"session={_FULL_UUID}" in result.output

    def test_agent_status_does_not_report_normal_one_shot_close_as_error(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [{"id": _FULL_UUID}]
        mock_client.get_session.return_value = {
            "id": _FULL_UUID,
            "status": "completed",
            "project_id": "p1",
            "agent_slug": "persona",
            "live_activity": {
                "status": "completed",
                "phase": "completed",
                "summary": "Streaming one-shot completed",
                "termination_reason": "streaming_one_shot_closed",
            },
        }

        with patch("cli.commands.agent.STClient", return_value=mock_client):
            result = runner.invoke(app, ["agent", "status", _FULL_UUID[:8]])

        assert result.exit_code == 0, result.output
        assert "AGENT_SESSION" in result.output
        assert "AGENT_ERROR" not in result.output

    def test_agent_stop_resolves_short_id(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [{"id": _FULL_UUID}]
        mock_client.close_session.return_value = {"id": _FULL_UUID, "status": "completed"}

        with patch("cli.commands.agent.STClient", return_value=mock_client):
            result = runner.invoke(app, ["agent", "stop", _FULL_UUID[:8]])

        assert result.exit_code == 0, result.output
        mock_client.close_session.assert_called_once_with(_FULL_UUID)


class TestSessionEventsResolvesShortId:
    """`st session-events <short-id>` should also work directly."""

    def test_session_events_resolves_short_id(self) -> None:
        mock_client = MagicMock()
        mock_client.list_sessions.return_value = [{"id": _FULL_UUID}]

        # `session-events` does not hold its own STClient; the resolver
        # constructs one on demand via `cli.client.STClient`.
        with (
            patch("cli.client.STClient", return_value=mock_client),
            patch(
                "cli.commands.session_events.get_session_events",
                return_value={"events": [], "total": 0, "max_turn": 0},
            ) as mock_get_events,
        ):
            result = runner.invoke(app, ["session-events", _FULL_UUID[:8]])

        assert result.exit_code == 0, result.output
        # Resolver expanded the short prefix to the full UUID before the API call.
        called_session_id = mock_get_events.call_args.args[0]
        assert called_session_id == _FULL_UUID

    def test_session_events_accepts_limit_alias_for_page_size(self) -> None:
        with patch(
            "cli.commands.session_events.get_session_events",
            return_value={"events": [], "total": 0, "max_turn": 0},
        ) as mock_get_events:
            result = runner.invoke(app, ["session-events", _FULL_UUID, "--limit", "50"])

        assert result.exit_code == 0, result.output
        assert mock_get_events.call_args.args[4] == 50
