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



def test_removed_health_is_absent_from_discovery_and_dispatch():
    from cli.lib.usage import collect_usage_specs

    root = get_command(app)
    assert isinstance(root, TyperGroup)
    ctx = typer.Context(root)
    assert "health" not in root.list_commands(ctx)
    assert root.get_command(ctx, "health") is None
    assert not any(spec.surface.startswith("st.health") for spec in collect_usage_specs(app))
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 2
    assert "No such command" in result.output


# Agents read every help page into context. Caps keep prose terse; examples and options carry syntax.
MAX_DESCRIPTION_CHARS = 600
MAX_PARAMETER_HELP_CHARS = 220
MAX_CHECK_HELP_CHARS = 1300


def _help_offenders() -> list[str]:
    from cli.extensions import ExtensionCommand

    offenders: list[str] = []

    def walk(command, path: list[str], parent) -> None:
        ctx = typer.Context(command, info_name=path[-1] if path else "st", parent=parent)
        name = " ".join(["st", *path])
        if path and len(command.help or "") > MAX_DESCRIPTION_CHARS:
            offenders.append(f"{name}: description {len(command.help)} chars")
        for param in command.params:
            if len(getattr(param, "help", None) or "") > MAX_PARAMETER_HELP_CHARS:
                offenders.append(f"{name} {param.name}: help {len(param.help)} chars")
        if hasattr(command, "list_commands"):
            for child_name in command.list_commands(ctx):
                child = command.get_command(ctx, child_name)
                if child is not None and not child.hidden and not isinstance(child, ExtensionCommand):
                    walk(child, [*path, child_name], ctx)

    walk(get_command(app), [], None)
    return offenders


def test_every_help_page_stays_within_agent_budget() -> None:
    offenders = _help_offenders()
    assert not offenders, (
        f"Help is agent context: keep descriptions <= {MAX_DESCRIPTION_CHARS} and option help <= "
        f"{MAX_PARAMETER_HELP_CHARS} chars; state rules once, tersely, and drop narration. " + "; ".join(offenders)
    )


def test_check_help_stays_within_agent_budget() -> None:
    from cli.commands.check_dispatch import help_text

    assert len(help_text("a|b|c")) <= MAX_CHECK_HELP_CHARS


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["ready", "--help"], ("cwd or -P", "[TRIAGE]", "suggested next pickup")),
        (["list", "--help"], ("cwd or -P", "ordered by priority", "completed_at")),
        (["vcs", "publication", "--help"], ("--hold and --release change it",)),
    ],
)
def test_help_answers_what_testers_asked(argv: list[str], expected: tuple[str, ...]) -> None:
    result = runner.invoke(app, argv, terminal_width=200)

    assert result.exit_code == 0
    output = " ".join(result.output.split())
    for text in expected:
        assert text in output
    assert "Read-only lightweight" not in output


def test_task_rows_show_the_full_status() -> None:
    from cli._formatters_compact import format_compact_task

    row = format_compact_task({"id": "task-1", "project_id": "summitflow", "status": "completed", "title": "x"})

    assert " completed " in row


def test_rebuild_help_says_it_deploys_committed_head() -> None:
    result = runner.invoke(app, ["service", "rebuild", "--help"], terminal_width=200)

    assert result.exit_code == 0
    assert "committed local HEAD (st commit first; no push needed)" in " ".join(result.output.split())
