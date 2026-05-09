"""Tests for task context compatibility aliases."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands.tasks import app

runner = CliRunner()


def test_task_get_alias_routes_to_context() -> None:
    client = MagicMock()
    with (
        patch("cli.commands.tasks.STClient", return_value=client),
        patch("cli.commands.tasks_context.get_task_context") as mock_get_context,
    ):
        result = runner.invoke(app, ["get", "task-123"])

    assert result.exit_code == 0
    mock_get_context.assert_called_once_with("task-123", None, client)
