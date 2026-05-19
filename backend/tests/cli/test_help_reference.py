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

    def test_claim_and_abandon_help_keep_examples_readable(self) -> None:
        claim = runner.invoke(app, ["claim", "--help"])
        abandon = runner.invoke(app, ["abandon", "--help"])
        feedback_resolve = runner.invoke(app, ["feedback", "resolve", "--help"])

        assert claim.exit_code == 0
        assert abandon.exit_code == 0
        assert feedback_resolve.exit_code == 0
        assert "Examples:\n    st claim task-abc123" in claim.output
        assert "Examples:\n    st abandon 1.1 -t task-abc123" in abandon.output
        assert "Examples:\n    st feedback resolve a1b2c3d4" in feedback_resolve.output
        assert "Examples:   st claim" not in claim.output
        assert "Examples:   st abandon" not in abandon.output
        assert "Examples:   st feedback resolve" not in feedback_resolve.output
