"""Root commands import their module on first use, and root help never imports them."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import typer
import typer.main
from typer.core import TyperGroup

from cli import main as cli_main

BACKEND = Path(__file__).parents[2]


@pytest.mark.parametrize("name", sorted(cli_main.LAZY_COMMANDS))
def test_each_lazy_entry_loads_its_real_command(name: str) -> None:
    hidden = cli_main.LAZY_COMMANDS[name][4]
    command = cli_main._lazy_command(name)

    assert command.name == name
    assert command.callback is not cli_main._lazy_placeholder
    assert "unavailable" not in (command.help or "")
    assert command.hidden == hidden


def test_root_group_resolves_real_command_but_lists_placeholders() -> None:
    group = typer.main.get_command(cli_main.app)
    assert isinstance(group, TyperGroup)
    ctx = typer.Context(group)

    assert group.get_command(ctx, "pulse") is cli_main._lazy_command("pulse")
    assert "pulse" in group.list_commands(ctx)


def test_root_help_imports_no_command_module() -> None:
    script = (
        "import sys\n"
        "from typer.testing import CliRunner\n"
        "from cli.main import app\n"
        "result = CliRunner().invoke(app, ['--help'])\n"
        "assert result.exit_code == 0, result.output\n"
        "assert 'pulse' in result.output and 'snaps' in result.output\n"
        "print(sorted(m for m in sys.modules if m.startswith('cli.commands.')))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_usage_walk_loads_lazy_command_surfaces() -> None:
    from cli.lib.usage import collect_usage_specs

    surfaces = {spec.surface for spec in collect_usage_specs(cli_main.app)}

    assert {"st.commit", "st.pulse", "st.lease"} <= surfaces
