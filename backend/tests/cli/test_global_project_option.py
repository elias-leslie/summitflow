"""`st <command> ... -P X` means `st -P X <command> ...` unless the command owns -P."""

from __future__ import annotations

import pytest
import typer

from cli.main import app, hoist_global_project


@pytest.fixture
def root() -> tuple[object, typer.Context]:
    group = typer.main.get_command(app)
    return group, typer.Context(group)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["ready", "-P", "x"], ["-P", "x", "ready"]),
        (["ready", "--project=x"], ["--project=x", "ready"]),
        (["lease", "--list", "-P", "x"], ["-P", "x", "lease", "--list"]),
        (["context", "task-1", "--project", "x"], ["--project", "x", "context", "task-1"]),
        # Already global, or no subcommand: unchanged.
        (["-P", "x", "ready"], ["-P", "x", "ready"]),
        (["-P", "x"], ["-P", "x"]),
        # Commands with their own -P keep it.
        (["sessions", "show", "abc", "-P", "x"], ["sessions", "show", "abc", "-P", "x"]),
        (["pulse", "-P", "x"], ["pulse", "-P", "x"]),
        # Passthrough after `--` is never touched.
        (["check", "pytest", "--", "-P", "x"], ["check", "pytest", "--", "-P", "x"]),
    ],
)
def test_project_option_is_hoisted_only_for_commands_without_their_own(root, argv, expected) -> None:
    group, ctx = root
    assert hoist_global_project(group, ctx, argv) == expected
