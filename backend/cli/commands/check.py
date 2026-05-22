"""Canonical quality-check command surface."""

from __future__ import annotations

import shutil  # noqa: F401  (tests patch cli.commands.check.shutil)
import subprocess  # noqa: F401  (tests patch cli.commands.check.subprocess)
from pathlib import Path

import typer

from ..lib.architecture_check import run_architecture_check
from ..lib.cleanroom import main as cleanroom_main
from ..lib.usage import usage
from ..output import output_error
from .check_changed import _changed_args, _changed_files, _skip_reason
from .check_codeql import (
    _emit_codeql_result,
    _fetch_codeql_alerts,
    _fetch_codeql_ref,
    _fetch_codeql_repo,
    _parse_codeql_args,
)
from .check_constants import _FIX_ARGS, _TOOL_SELECTIONS
from .check_runner import (
    _normalize_explicit_args,
    _resolve_repo_root,
    _run_tool,
    _tool_configs,
    _workdir,
)

app = typer.Typer(
    help=(
        "Quality checks through st. Use st check for repo gates; never run raw "
        "pytest, Vitest, Biome, TSC, Ruff, SQLFluff, Squawk, or legacy dt first."
    ),
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
    add_help_option=False,
)


def _extract_check_options(args: list[str]) -> tuple[list[str], bool, bool]:
    changed_only = False
    args = [
        arg
        for arg in args
        if not (arg in {"--changed-only", "-d"} and (changed_only := True))
    ]
    fix = "--fix" in args
    args = ["--fix"] if args == ["--fix"] else [arg for arg in args if arg != "--fix"]
    return (["--quick"] if changed_only and not args else args), changed_only, fix


def _run_codeql_alert_check(args: list[str]) -> int:
    """Run the CodeQL alert check using this module's _resolve_repo_root (patchable by tests)."""
    explicit_ref, parse_code = _parse_codeql_args(args)
    if parse_code == -1:
        return 0
    if parse_code != 0:
        return parse_code
    root = _resolve_repo_root()
    repo = _fetch_codeql_repo(root)
    if repo is None:
        from ..details import display_path, write_details
        details = write_details(
            root,
            "codeql",
            "GitHub CLI is unavailable, unauthenticated, or cannot resolve this repository.",
        )
        print(
            f"CODEQL:FAIL:127|details:{display_path(root, details)}|"
            "hint:install/auth gh and run from a GitHub repository"
        )
        return 127
    ref = explicit_ref if explicit_ref is not None else _fetch_codeql_ref(root)
    alerts, error, exit_code = _fetch_codeql_alerts(root, repo, ref)
    return _emit_codeql_result(root, repo, ref, alerts, error, exit_code)


def _run_selected(
    selected: list[str],
    configs: dict[str, dict[str, object]],
    *,
    fix: bool,
    changed_only: bool,
) -> int:
    root = _resolve_repo_root()
    changed_files = _changed_files(root) if changed_only else []
    failures = int(run_architecture_check(root, changed_files if changed_only else None) != 0)
    for name in selected:
        config = configs[name]
        cwd = _workdir(root, config)
        scoped_args = _changed_args(name, root, cwd, config, changed_files)
        skip_reason = _skip_reason(
            name,
            config,
            changed_only=changed_only,
            changed_files=changed_files,
            scoped_args=scoped_args,
        )
        if skip_reason:
            label = config.get("label") or name.upper()
            print(f"{label!s}:SKIP:{name}:{skip_reason}")
            continue
        failures += int(
            _run_tool(name, config, [*scoped_args, *(_FIX_ARGS.get(name, []) if fix else [])]) != 0
        )
    return int(failures != 0)


def _selected_tool_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, object],
    changed_only: bool,
    fix: bool,
    args: list[str],
) -> tuple[list[str], bool]:
    stripped = args[1:]
    explicit_args = _normalize_explicit_args(root, cwd, stripped)
    changed_files = _changed_files(root) if changed_only else []
    scoped_args = [] if explicit_args else _changed_args(name, root, cwd, config, changed_files)
    skip_reason = _skip_reason(
        name,
        config,
        changed_only=changed_only,
        changed_files=changed_files,
        scoped_args=scoped_args,
        explicit_args=bool(explicit_args),
    )
    if skip_reason:
        label = config.get("label") or name.upper()
        print(f"{label!s}:SKIP:{name}:{skip_reason}")
        return [], True
    return [*explicit_args, *scoped_args, *(_FIX_ARGS.get(name, []) if fix else [])], False


def _run_named_tool(
    first: str,
    args: list[str],
    configs: dict[str, dict[str, object]],
    *,
    changed_only: bool,
    fix: bool,
) -> int:
    if first == "codeql":
        return _run_codeql_alert_check(args[1:])
    if first not in configs:
        return 2
    root = _resolve_repo_root()
    config = configs[first]
    cwd = _workdir(root, config)
    extra_args, skipped = _selected_tool_args(first, root, cwd, config, changed_only, fix, args)
    if skipped:
        return 0
    return _run_tool(first, config, extra_args)


@app.callback(invoke_without_command=True)
@usage(
    surface="st.check",
    cmd="st check --quick --changed-only",
    when="pre-edit gates; pre-commit; before reporting done",
    precautions=(
        "use st check for all quality gates (ruff/biome/tsc/types/pytest)",
        "use st check codeql to verify GitHub CodeQL alert state after code-scanning work",
        "never run raw pytest/vitest/biome/tsc/ruff/sqlfluff/squawk",
    ),
    tier="mandate",
)
def _help_text(names: str) -> str:
    return (
        """Quality checks through st

Required path:
  Use st check for repo gates.
  Never run raw pytest, Vitest, Biome, TSC, Ruff, SQLFluff, Squawk, or legacy dt first.

Usage:
  st check --check
  st check --changed-only
  st check --quick [--changed-only]
  st check --frontend-only
  st check codeql [--ref refs/heads/main]
  st check cleanroom -- <command>
  st check <"""
        + names
        + "> [-- <tool args>]\n"
    )


def _handle_check_args(ctx: typer.Context, configs: dict[str, dict[str, object]]) -> int:
    args = list(ctx.args)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(_help_text("|".join(sorted(configs))))
        return 0

    args, changed_only, fix = _extract_check_options(args)
    first = args[0]
    if first == "cleanroom":
        return cleanroom_main(["--project-root", str(_resolve_repo_root()), *args[1:]])

    if first == "codeql":
        return _run_codeql_alert_check(args[1:])
    if first in configs:
        return _run_named_tool(first, args, configs, changed_only=changed_only, fix=fix)

    selection = _TOOL_SELECTIONS.get(first)
    if selection is None:
        output_error(f"Unknown st check mode/tool: {first}")
        return 2
    names, selected_fix = selection
    selected = [name for name in names if name in configs]
    return _run_selected(selected, configs, fix=fix or selected_fix, changed_only=changed_only)


def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands."""
    if ctx.invoked_subcommand is not None:
        return
    raise typer.Exit(_handle_check_args(ctx, _tool_configs()))
