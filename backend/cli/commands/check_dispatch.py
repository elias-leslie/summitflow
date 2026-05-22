"""Argument dispatch for the st check command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import typer

ToolConfig = dict[str, object]
ToolConfigs = dict[str, ToolConfig]
ToolSelection = tuple[tuple[str, ...], bool]


class SkipReason(Protocol):
    def __call__(
        self,
        name: str,
        config: ToolConfig,
        *,
        changed_only: bool,
        changed_files: list[str],
        scoped_args: list[str],
        explicit_args: bool = False,
    ) -> str | None: ...


@dataclass(frozen=True)
class CheckRuntime:
    fix_args: dict[str, list[str]]
    tool_selections: dict[str, ToolSelection]
    cleanroom_main: Callable[[list[str]], int]
    run_architecture_check: Callable[[Path, list[str] | None], int]
    output_error: Callable[[str], None]
    resolve_repo_root: Callable[[], Path]
    workdir: Callable[[Path, ToolConfig], Path]
    normalize_explicit_args: Callable[[Path, Path, list[str]], list[str]]
    changed_files: Callable[[Path], list[str]]
    changed_args: Callable[[str, Path, Path, ToolConfig, list[str]], list[str]]
    skip_reason: SkipReason
    run_tool: Callable[[str, ToolConfig, list[str]], int]
    run_codeql_alert_check: Callable[[list[str]], int]


def extract_check_options(args: list[str]) -> tuple[list[str], bool, bool]:
    changed_only = False
    args = [
        arg
        for arg in args
        if not (arg in {"--changed-only", "-d"} and (changed_only := True))
    ]
    fix = "--fix" in args
    args = ["--fix"] if args == ["--fix"] else [arg for arg in args if arg != "--fix"]
    return (["--quick"] if changed_only and not args else args), changed_only, fix


def run_selected(
    selected: list[str],
    configs: ToolConfigs,
    *,
    fix: bool,
    changed_only: bool,
    runtime: CheckRuntime,
) -> int:
    root = runtime.resolve_repo_root()
    changed_files = runtime.changed_files(root) if changed_only else []
    failures = int(runtime.run_architecture_check(root, changed_files if changed_only else None) != 0)
    for name in selected:
        config = configs[name]
        cwd = runtime.workdir(root, config)
        scoped_args = runtime.changed_args(name, root, cwd, config, changed_files)
        skip_reason = runtime.skip_reason(
            name,
            config,
            changed_only=changed_only,
            changed_files=changed_files,
            scoped_args=scoped_args,
        )
        if skip_reason:
            print(f"{config.get('label') or name.upper()!s}:SKIP:{name}:{skip_reason}")
            continue
        fix_args = runtime.fix_args.get(name, []) if fix else []
        failures += int(runtime.run_tool(name, config, [*scoped_args, *fix_args]) != 0)
    return int(failures != 0)


def selected_tool_args(
    name: str,
    root: Path,
    cwd: Path,
    config: ToolConfig,
    changed_only: bool,
    fix: bool,
    args: list[str],
    *,
    runtime: CheckRuntime,
) -> tuple[list[str], bool]:
    explicit_args = runtime.normalize_explicit_args(root, cwd, args[1:])
    changed_files = runtime.changed_files(root) if changed_only else []
    scoped_args = [] if explicit_args else runtime.changed_args(name, root, cwd, config, changed_files)
    skip_reason = runtime.skip_reason(
        name,
        config,
        changed_only=changed_only,
        changed_files=changed_files,
        scoped_args=scoped_args,
        explicit_args=bool(explicit_args),
    )
    if skip_reason:
        print(f"{config.get('label') or name.upper()!s}:SKIP:{name}:{skip_reason}")
        return [], True
    return [*explicit_args, *scoped_args, *(runtime.fix_args.get(name, []) if fix else [])], False


def run_named_tool(
    first: str,
    args: list[str],
    configs: ToolConfigs,
    *,
    changed_only: bool,
    fix: bool,
    runtime: CheckRuntime,
) -> int:
    if first == "codeql":
        return runtime.run_codeql_alert_check(args[1:])
    if first not in configs:
        return 2
    root = runtime.resolve_repo_root()
    config = configs[first]
    cwd = runtime.workdir(root, config)
    extra_args, skipped = selected_tool_args(
        first, root, cwd, config, changed_only, fix, args, runtime=runtime
    )
    return 0 if skipped else runtime.run_tool(first, config, extra_args)


def help_text(names: str) -> str:
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


def handle_check_args(
    ctx: typer.Context,
    configs: ToolConfigs,
    *,
    runtime: CheckRuntime,
) -> int:
    args = list(ctx.args)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(help_text("|".join(sorted(configs))))
        return 0

    args, changed_only, fix = extract_check_options(args)
    first = args[0]
    if first == "cleanroom":
        return runtime.cleanroom_main(["--project-root", str(runtime.resolve_repo_root()), *args[1:]])
    if first == "codeql":
        return runtime.run_codeql_alert_check(args[1:])
    if first in configs:
        return run_named_tool(first, args, configs, changed_only=changed_only, fix=fix, runtime=runtime)

    selection = runtime.tool_selections.get(first)
    if selection is None:
        runtime.output_error(f"Unknown st check mode/tool: {first}")
        return 2
    names, selected_fix = selection
    selected = [name for name in names if name in configs]
    return run_selected(selected, configs, fix=fix or selected_fix, changed_only=changed_only, runtime=runtime)
