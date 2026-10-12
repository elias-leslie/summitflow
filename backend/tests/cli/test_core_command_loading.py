"""Core task-lifecycle commands load for real, not as the fail-soft unavailable stub."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli import main as cli_main

runner = CliRunner()


@pytest.mark.parametrize("module_name", ["claim", "done", "tasks", "pulse"])
def test_core_command_modules_import(module_name: str) -> None:
    assert not isinstance(cli_main._COMMANDS[module_name], cli_main._FailedCommandModule)


@pytest.mark.parametrize("command", ["claim", "done", "create", "commit", "context", "critique", "pulse"])
def test_core_commands_render_help_without_unavailable_stub(command: str) -> None:
    result = runner.invoke(cli_main.app, [command, "--help"])

    assert result.exit_code == 0, result.output
    assert "unavailable" not in result.output


