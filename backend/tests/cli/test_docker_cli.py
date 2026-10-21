"""Tests for Docker CLI commands."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from app.utils.nightshift_stack import StackResult
from cli.commands.docker import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def stack_unit_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.commands.docker.nightshift_stack.stack_installed", lambda: True)


class TestDockerStatus:
    @patch("cli.commands.docker._infra_status", new_callable=AsyncMock)
    def test_status_lists_observed_container_states(self, observed: AsyncMock) -> None:
        observed.side_effect = [SimpleNamespace(state=state) for state in ("stopped", "unknown", "running")]
        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "DOCKER:STATUS" in result.stdout
        assert "running" in result.stdout
        assert "postgres:stopped" in result.stdout
        assert "redis:unknown" in result.stdout


class TestDockerStackActions:
    @pytest.mark.parametrize(
        ("command", "action"), [("up", "start"), ("down", "stop"), ("restart", "restart")]
    )
    @patch("cli.commands.docker.nightshift_stack.request_stack")
    def test_actions_go_through_nightshift(
        self, mock_request: MagicMock, command: str, action: str
    ) -> None:
        mock_request.return_value = StackResult(success=True, message="done")

        result = runner.invoke(app, [command])

        assert result.exit_code == 0
        mock_request.assert_called_once_with(action)

    @patch("cli.commands.docker.nightshift_stack.request_stack")
    def test_failure_exits_nonzero_and_service_is_called_out(self, mock_request: MagicMock) -> None:
        mock_request.return_value = StackResult(success=False, message="refused")

        result = runner.invoke(app, ["restart", "hatchet"])

        assert result.exit_code == 1
        assert "whole stack" in result.stdout
        assert "refused" in result.stdout


class TestBeforeNightshiftInstall:
    """Without summitflow-stack.service the controls keep using docker compose."""

    @pytest.mark.parametrize("command", ["up", "down", "restart"])
    @patch("cli.commands.docker.subprocess.run")
    @patch("cli.commands.docker.nightshift_stack.request_stack")
    def test_compose_is_used(
        self, mock_request: MagicMock, mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        monkeypatch.setattr("cli.commands.docker.nightshift_stack.stack_installed", lambda: False)
        mock_run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, [command])

        assert result.exit_code == 0
        mock_request.assert_not_called()
        assert list(mock_run.call_args.args[0][:2]) == ["docker", "compose"]
