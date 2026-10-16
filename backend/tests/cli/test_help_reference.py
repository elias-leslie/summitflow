"""Root help stays compact; command-specific help carries details."""

from __future__ import annotations

import pytest
import typer
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
        for text in ("pulse", "pause <id>", "vcs doctor", "check", "browser"):
            assert text in CLI_REFERENCE
        assert "pulse --gate" not in CLI_REFERENCE

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
        ctx = typer.Context(root)
        command = root.get_command(ctx, name)
        task_group = root.get_command(ctx, "task")
        assert command is not None
        assert isinstance(task_group, TyperGroup)
        owner = task_group.commands[name]

        assert command.help
        assert command.help == owner.help
        assert command.short_help == owner.short_help
        assert command.epilog == owner.epilog
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == 0
        assert "live schema" in result.output

