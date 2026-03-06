"""Test that CLI_REFERENCE in main.py stays up to date with registered commands.

This test ensures that whenever new commands or subcommands are added to the CLI,
the CLI_REFERENCE help text is also updated. Prevents --help from becoming stale.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

try:
    from cli.main import CLI_REFERENCE, app
except ImportError as e:
    pytest.skip(f"Cannot import cli.main (missing dependency: {e})", allow_module_level=True)

runner = CliRunner()


def get_all_command_names() -> set[str]:
    """Extract all registered command names from the typer app."""
    commands = set()

    # Root level commands
    for cmd in app.registered_commands:
        callback = cmd.callback
        name = cmd.name or (callback.__name__ if callback is not None else "")
        commands.add(name)

    # Subcommand groups
    for group in app.registered_groups:
        group_name = group.name
        if group_name and not getattr(group, "hidden", False):
            # Add group name
            commands.add(group_name)
            # Add subcommands within group
            if hasattr(group, "typer_instance"):
                typer_instance = group.typer_instance
                if typer_instance is not None:
                    for subcmd in typer_instance.registered_commands:
                        subcmd_callback = subcmd.callback
                        subname = subcmd.name or (
                            subcmd_callback.__name__ if subcmd_callback is not None else ""
                        )
                        commands.add(f"{group_name} {subname}")

    return commands


class TestCLIReferenceComplete:
    """Tests to ensure CLI_REFERENCE documents all commands."""

    def test_all_root_commands_documented(self) -> None:
        """Verify all root-level commands appear in CLI_REFERENCE."""
        missing = []
        for cmd in app.registered_commands:
            callback = cmd.callback
            name = cmd.name or (callback.__name__ if callback is not None else "")
            # Skip hidden commands (deprecated/removed commands)
            if getattr(cmd, "hidden", False):
                continue
            # Check if command name appears in reference (with reasonable context)
            if name not in CLI_REFERENCE:
                missing.append(name)

        assert not missing, (
            f"Commands missing from CLI_REFERENCE: {missing}\n"
            "Update CLI_REFERENCE in cli/main.py to include these commands."
        )

    def test_all_subcommand_groups_documented(self) -> None:
        """Verify all subcommand groups appear in CLI_REFERENCE."""
        missing = []
        for group in app.registered_groups:
            name = group.name
            # Check group name appears (case insensitive), skip hidden groups
            if (
                name
                and not getattr(group, "hidden", False)
                and name.upper() not in CLI_REFERENCE.upper()
            ):
                missing.append(name)

        assert not missing, (
            f"Subcommand groups missing from CLI_REFERENCE: {missing}\n"
            "Update CLI_REFERENCE in cli/main.py to include these groups."
        )

    def test_core_workflow_commands_have_examples(self) -> None:
        """Verify core workflow commands have examples in CLI_REFERENCE."""
        core_commands = [
            "ready",
            "claim",
            "subtask list",
            "step pass",
            "subtask pass",
            "done",
        ]
        examples_section = (
            CLI_REFERENCE.split("EXAMPLES:")[1] if "EXAMPLES:" in CLI_REFERENCE else ""
        )

        missing_examples = []
        for cmd in core_commands:
            # Check command appears in examples (fuzzy match)
            cmd_parts = cmd.split()
            if not any(part in examples_section for part in cmd_parts):
                missing_examples.append(cmd)

        assert not missing_examples, (
            f"Core commands missing from EXAMPLES section: {missing_examples}\n"
            "These are frequently used - add examples to CLI_REFERENCE."
        )

    def test_global_flags_documented(self) -> None:
        """Verify global flags are documented in CLI_REFERENCE."""
        required_flags = ["--compact", "--human", "--project", "--progress-only"]

        missing = [flag for flag in required_flags if flag not in CLI_REFERENCE]

        assert not missing, (
            f"Global flags missing from CLI_REFERENCE: {missing}\n"
            "Update the FLAGS line in CLI_REFERENCE."
        )

    def test_cli_reference_not_empty(self) -> None:
        """Basic sanity check that CLI_REFERENCE has content."""
        assert len(CLI_REFERENCE) > 500, (
            "CLI_REFERENCE seems too short - check it wasn't accidentally truncated"
        )
        assert "TASKS" in CLI_REFERENCE, "CLI_REFERENCE missing TASKS section"
        assert "SUBTASK:" in CLI_REFERENCE, "CLI_REFERENCE missing SUBTASK section"
        assert "STEP:" in CLI_REFERENCE, "CLI_REFERENCE missing STEP section"

    def test_rendered_help_preserves_literal_bracketed_tokens(self) -> None:
        """Rendered help should show literal bracketed placeholders, not eat them as Rich markup."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "[work]" in result.stdout
        assert "projects [list|current|get|create|update|delete]" in result.stdout
