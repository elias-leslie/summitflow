"""Tests for Docker CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands.docker import app

runner = CliRunner()


class TestDockerStatus:
    """Tests for st docker status."""

    @patch("cli.commands.docker.read_docker_mode")
    @patch("cli.commands.docker._compose_json")
    def test_status_prints_mode(self, mock_compose_json: MagicMock, mock_read_mode: MagicMock) -> None:
        mock_read_mode.return_value = "dev"
        mock_compose_json.return_value = []

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "DOCKER:MODE:dev" in result.stdout


class TestDockerUp:
    """Tests for st docker up."""

    @patch("cli.commands.docker._run")
    @patch("cli.commands.docker.compose_env")
    @patch("cli.commands.docker.write_docker_mode")
    @patch("cli.commands.docker.read_docker_mode")
    def test_up_uses_saved_mode_when_unspecified(
        self,
        mock_read_mode: MagicMock,
        mock_write_mode: MagicMock,
        mock_compose_env: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        mock_read_mode.return_value = "dev"
        mock_compose_env.return_value = {"PATH": "/usr/bin"}

        result = runner.invoke(app, ["up"])

        assert result.exit_code == 0
        mock_write_mode.assert_called_once_with("dev")
        args = mock_run.call_args.args[0]
        assert "docker-compose.dev.yml" in " ".join(args)
        assert mock_run.call_args.kwargs["env"] == {"PATH": "/usr/bin"}

    def test_up_rejects_conflicting_mode_flags(self) -> None:
        result = runner.invoke(app, ["up", "--dev", "--prod"])

        assert result.exit_code != 0
        assert "Choose either --dev or --prod" in result.output
