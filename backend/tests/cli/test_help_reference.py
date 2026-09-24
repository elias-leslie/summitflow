"""Root help stays compact; command-specific help carries details."""

from __future__ import annotations

import pytest
from typer.core import TyperGroup
from typer.main import get_command
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

    @pytest.mark.parametrize("name", ["create", "verify"])
    def test_root_task_help_preserves_owner_description(self, name: str) -> None:
        root = get_command(app)
        assert isinstance(root, TyperGroup)
        command = root.commands[name]
        task_group = root.commands["task"]
        assert isinstance(task_group, TyperGroup)
        owner = task_group.commands[name]

        assert command.help
        assert command.help == owner.help
        assert command.short_help == owner.short_help
        assert command.epilog == owner.epilog
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == 0
        assert "live schema" in result.output

    def test_global_output_help_explains_precedence(self) -> None:
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "requires --no-compact" in result.output
        assert "Global options precede the command" in result.output

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
