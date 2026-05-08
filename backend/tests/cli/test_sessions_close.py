"""Tests for `st sessions close`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_sessions_close_calls_client_and_prints_response() -> None:
    mock_client = MagicMock()
    # The CLI resolves short prefixes via list_sessions before closing so the
    # short ID printed by `st sessions list` works directly.
    mock_client.list_sessions.return_value = [{"id": "sess-1"}]
    mock_client.close_session.return_value = {
        "id": "sess-1",
        "status": "completed",
        "message": "Session closed successfully",
    }

    with patch("cli.commands.sessions.STClient", return_value=mock_client):
        result = runner.invoke(app, ["sessions", "close", "sess-1"])

    assert result.exit_code == 0
    assert "Session closed successfully" in result.output
    mock_client.close_session.assert_called_once_with("sess-1")
