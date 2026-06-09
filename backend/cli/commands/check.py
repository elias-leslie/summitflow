"""Canonical quality-check command surface."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import typer

from ..details import display_path, summary_hint, write_details
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
from .check_dispatch import (
    CheckRuntime,
    extract_check_options,
    handle_check_args,
    help_text,
    run_named_tool,
    run_selected,
    selected_tool_args,
)
from .check_execution import (
    adjusted_tool_args,
    tool_env,
    tool_output,
    tool_result_line,
)
from .check_runner import (
    _normalize_explicit_args,
    _resolve_repo_root,
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


def _resolve_command(binary: str, root: Path, cwd: Path, base_args: list[str]) -> list[str]:
    # npx foo -> search node_modules for foo, not for npx itself.
    if binary == "npx" and base_args:
        tool = base_args[0]
        for search_root in (cwd, root / "frontend", root):
            npx_candidate = search_root / "node_modules" / ".bin" / tool
            if npx_candidate.exists():
                return [str(npx_candidate), *base_args[1:]]
        npx = shutil.which("npx")
        return [npx or "npx", "--no-install", *base_args]

    for search_root in (cwd, root / "frontend", root):
        for candidate in (
            search_root / "node_modules" / ".bin" / binary,
            search_root / ".venv" / "bin" / binary,
        ):
            if candidate.exists():
                return [str(candidate), *base_args]

    resolved = shutil.which(binary)
    return [resolved or binary, *base_args]


def _run_tool(name: str, config: dict[str, object], extra_args: list[str]) -> int:
    root = _resolve_repo_root()
    cwd = _workdir(root, config)
    binary = str(config.get("binary") or name)
    base_args = shlex.split(str(config.get("args") or ""))
    base_args, extra_args = adjusted_tool_args(name, base_args, extra_args, root)
    command = [*_resolve_command(binary, root, cwd, base_args), *extra_args]
    label = str(config.get("label") or name.upper())
    print(f"{label}:{name}:start")

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=tool_env(root, os.environ, name),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        output = f"{type(exc).__name__}: {exc}"
        details = write_details(root, name, output)
        print(
            tool_result_line(
                label,
                name,
                127,
                display_path(root, details),
                summary_hint(output),
            )
        )
        return 127
    output = tool_output(result.stdout, result.stderr)
    details = write_details(root, name, output)
    print(
        tool_result_line(
            label,
            name,
            result.returncode,
            display_path(root, details),
            summary_hint(output),
        )
    )
    return result.returncode


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


def _runtime() -> CheckRuntime:
    return CheckRuntime(
        fix_args=_FIX_ARGS,
        tool_selections=_TOOL_SELECTIONS,
        cleanroom_main=cleanroom_main,
        run_architecture_check=run_architecture_check,
        output_error=output_error,
        resolve_repo_root=_resolve_repo_root,
        workdir=_workdir,
        normalize_explicit_args=_normalize_explicit_args,
        changed_files=_changed_files,
        changed_args=_changed_args,
        skip_reason=_skip_reason,
        run_tool=_run_tool,
        run_codeql_alert_check=_run_codeql_alert_check,
    )


def _extract_check_options(args: list[str]) -> tuple[list[str], bool, bool]:
    return extract_check_options(args)


def _run_selected(
    selected: list[str],
    configs: dict[str, dict[str, object]],
    *,
    fix: bool,
    changed_only: bool,
) -> int:
    return run_selected(selected, configs, fix=fix, changed_only=changed_only, runtime=_runtime())


def _selected_tool_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, object],
    changed_only: bool,
    fix: bool,
    args: list[str],
) -> tuple[list[str], bool]:
    return selected_tool_args(
        name,
        root,
        cwd,
        config,
        changed_only,
        fix,
        args,
        runtime=_runtime(),
    )


def _run_named_tool(
    first: str,
    args: list[str],
    configs: dict[str, dict[str, object]],
    *,
    changed_only: bool,
    fix: bool,
) -> int:
    return run_named_tool(
        first,
        args,
        configs,
        changed_only=changed_only,
        fix=fix,
        runtime=_runtime(),
    )


@app.callback(invoke_without_command=True)
def _help_text(names: str) -> str:
    return help_text(names)


def _handle_check_args(ctx: typer.Context, configs: dict[str, dict[str, object]]) -> int:
    return handle_check_args(ctx, configs, runtime=_runtime())


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
def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands."""
    if ctx.invoked_subcommand is not None:
        return
    raise typer.Exit(_handle_check_args(ctx, _tool_configs()))
