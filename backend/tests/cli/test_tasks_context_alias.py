"""Hidden `st task get` alias is gone; only `st context` exposes task context."""

from __future__ import annotations

from typer.testing import CliRunner

from cli.commands.tasks import app

runner = CliRunner()


def test_task_get_alias_no_longer_registered() -> None:
    """The hidden `st task get` alias was removed in the agentic-friction cleanup."""
    result = runner.invoke(app, ["get", "task-123"])
    assert result.exit_code != 0
