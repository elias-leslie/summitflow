"""Root help stays compact; command-specific help carries details."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

try:
    from cli.main import CLI_REFERENCE, app
except ImportError as e:
    pytest.skip(f"Cannot import cli.main (missing dependency: {e})", allow_module_level=True)

runner = CliRunner()


class TestCLIReferenceCompact:
    def test_cli_reference_is_short_and_agent_focused(self) -> None:
        assert len(CLI_REFERENCE) < 500
        for text in ("pulse --gate", "pause <id>", "vcs doctor", "check", "browser"):
            assert text in CLI_REFERENCE

    def test_root_help_is_bounded(self) -> None:
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert len(result.output.splitlines()) <= 120
        assert "command-specific syntax" in result.output
        assert "EXAMPLES:" not in result.output
        assert "WORKFLOW: pulse" not in result.output

    def test_command_specific_help_keeps_task_creation_details(self) -> None:
        result = runner.invoke(app, ["create", "--help"])

        assert result.exit_code == 0
        assert "--plan" in result.output
        assert "--from-file" in result.output
