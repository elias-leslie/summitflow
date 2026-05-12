"""Canonical quality-check command surface."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import typer

from ..details import display_path, summary_hint, write_details
from ..lib.architecture_check import run_architecture_check
from ..lib.cleanroom import main as cleanroom_main
from ..lib.usage import usage
from ..output import output_error
from ..tool_registry import load_tool_registry

_TOOL_FILE_SUFFIXES: dict[str, set[str]] = {
    "pytest": {".py", ".pyi"},
    "types": {".py", ".pyi"},
    "ruff": {".py", ".pyi"},
    "biome": {
        ".css",
        ".js",
        ".json",
        ".jsonc",
        ".jsx",
        ".md",
        ".mdx",
        ".scss",
        ".ts",
        ".tsx",
    },
    "tsc": {".js", ".jsx", ".ts", ".tsx"},
    "vitest": {".js", ".jsx", ".ts", ".tsx"},
    "sqlfluff": {".sql"},
    "squawk": {".sql"},
}

_TOOL_CONFIG_PATHS: dict[str, set[str]] = {
    "pytest": {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"},
    "biome": {
        "biome.json",
        "biome.jsonc",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    },
    "tsc": {
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "tsconfig.build.json",
        "yarn.lock",
    },
    "vitest": {
        "package.json",
        "pnpm-lock.yaml",
        "vite.config.ts",
        "vitest.config.ts",
        "yarn.lock",
    },
}

def _is_pytest_test_path(path: Path) -> bool:
    return (
        path.suffix in {".py", ".pyi"}
        and (
            "tests" in path.parts
            or path.name.startswith("test_")
            or path.name.endswith("_test.py")
        )
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


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return Path.cwd()


def _tool_configs() -> dict[str, dict[str, Any]]:
    registry = load_tool_registry()
    configs: dict[str, dict[str, Any]] = {}
    for item in registry.get("tools", []):
        if not isinstance(item, dict):
            continue
        config = item.get("check")
        if not isinstance(config, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            configs[name] = config
    return configs


def _workdir(root: Path, config: dict[str, Any]) -> Path:
    kind = str(config.get("working_dir") or "")
    if kind == "backend" and (root / "backend").exists():
        return root / "backend"
    if kind == "frontend" and (root / "frontend").exists():
        return root / "frontend"
    if kind == "migrations":
        if (root / "backend" / "alembic").exists():
            return root / "backend"
        if (root / "alembic").exists():
            return root
    if kind == "test" and (root / "backend").exists():
        return root / "backend"
    return root


def _changed_files(root: Path) -> list[str]:
    override = os.environ.get("ST_CHECK_CHANGED_FILES", "").strip()
    if override:
        return sorted(
            {
                item.strip()
                for line in override.splitlines()
                for item in line.split(os.pathsep)
                if item.strip()
            }
        )
    files: set[str] = set()
    for args in (
        ["diff", "--name-only", "HEAD"],
        ["diff", "--cached", "--name-only"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            files.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(files)


def _path_allowed_for_tool(name: str, path: Path) -> bool:
    if name in {"ruff", "types"}:
        return path.suffix in {".py", ".pyi"}
    if name in {"sqlfluff", "squawk"}:
        return path.suffix == ".sql"
    return True


def _path_relevant_for_tool(name: str, rel_path: str) -> bool:
    path = Path(rel_path)
    if path.name in _TOOL_CONFIG_PATHS.get(name, set()):
        return True
    if name == "pytest":
        return _is_pytest_test_path(path)
    return path.suffix in _TOOL_FILE_SUFFIXES.get(name, set())


def _has_relevant_changed_files(name: str, changed_files: list[str]) -> bool:
    return any(_path_relevant_for_tool(name, rel_path) for rel_path in changed_files)


def _changed_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, Any],
    changed_files: list[str],
) -> list[str]:
    if not changed_files:
        return []
    if name != "pytest" and not config.get("pass_path"):
        return []
    paths: list[str] = []
    for rel_path in changed_files:
        absolute = (root / rel_path).resolve()
        if not absolute.exists() or not absolute.is_file():
            continue
        if name == "pytest" and not _is_pytest_test_path(Path(rel_path)):
            continue
        if name == "pytest" and absolute.name == "conftest.py":
            absolute = absolute.parent
        if absolute.is_relative_to(cwd.resolve()):
            relative = absolute.relative_to(cwd)
            if _path_allowed_for_tool(name, relative):
                rel_posix = relative.as_posix()
                if rel_posix not in paths:
                    paths.append(rel_posix)
    return paths


def _env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths: list[str] = []
    for candidate in (
        root / "backend" / ".venv" / "bin",
        root / ".venv" / "bin",
        root / "frontend" / "node_modules" / ".bin",
        root / "node_modules" / ".bin",
    ):
        if candidate.exists():
            paths.append(str(candidate))
    if paths:
        env["PATH"] = ":".join([*paths, env.get("PATH", "")])
    return env


def _tool_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _local_node_binary(root: Path, cwd: Path, binary: str) -> Path | None:
    for directory in (
        cwd / "node_modules" / ".bin",
        root / "frontend" / "node_modules" / ".bin",
        root / "node_modules" / ".bin",
    ):
        candidate = directory / binary
        if candidate.exists():
            return candidate
    return None


def _resolve_command(binary: str, root: Path, cwd: Path, base_args: list[str]) -> list[str]:
    if binary == "npx" and base_args:
        local_binary = _local_node_binary(root, cwd, base_args[0])
        if local_binary:
            return [str(local_binary), *base_args[1:]]
        npx = shutil.which("npx")
        return [npx or "npx", "--no-install", *base_args]
    venv_binary = cwd / ".venv" / "bin" / binary
    if venv_binary.exists():
        return [str(venv_binary), *base_args]
    local = _local_node_binary(root, cwd, binary)
    if local:
        return [str(local), *base_args]
    resolved = shutil.which(binary)
    return [resolved or binary, *base_args]


def _run_tool(name: str, config: dict[str, Any], extra_args: list[str]) -> int:
    root = _repo_root()
    cwd = _workdir(root, config)
    binary = str(config.get("binary") or name)
    base_args = shlex.split(str(config.get("args") or ""))
    if name == "biome" and any(not arg.startswith("-") for arg in extra_args):
        base_args = [arg for arg in base_args if arg != "."]
    if name == "pytest":
        extra_args = _pytest_extra_args(extra_args)
    command = [*_resolve_command(binary, root, cwd, base_args), *extra_args]
    label = str(config.get("label") or name.upper())
    print(f"{label}:{name}:start")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_env(root),
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
            f"{label}:FAIL:127|details:{display_path(root, details)}|hint:{summary_hint(output)}"
        )
        return 127
    output = _tool_output(result)
    details = write_details(root, name, output)
    print(
        f"{label}:{'OK' if result.returncode == 0 else 'FAIL'}:{result.returncode}|"
        f"details:{display_path(root, details)}|hint:{summary_hint(output)}"
    )
    return result.returncode


def _pytest_extra_args(extra_args: list[str]) -> list[str]:
    has_path_arg = any(arg and not arg.startswith("-") for arg in extra_args)
    has_cov_control = any(arg == "--no-cov" or arg.startswith("--cov") for arg in extra_args)
    if has_path_arg and not has_cov_control:
        return ["--no-cov", *extra_args]
    return extra_args


def _run_selected(
    selected: list[str],
    configs: dict[str, dict[str, Any]],
    *,
    fix: bool,
    changed_only: bool,
) -> int:
    root = _repo_root()
    changed_files = _changed_files(root) if changed_only else []
    failures = 1 if run_architecture_check(root, changed_files if changed_only else None) != 0 else 0
    for name in selected:
        config = configs[name]
        cwd = _workdir(root, config)
        scoped_args = _changed_args(name, root, cwd, config, changed_files)
        if changed_only and config.get("pass_path") and not scoped_args:
            print(f"{config.get('label') or name.upper()!s}:SKIP:{name}:no_changed_paths")
            continue
        if (
            changed_only
            and not config.get("pass_path")
            and not _has_relevant_changed_files(name, changed_files)
        ):
            label = config.get("label") or name.upper()
            print(f"{label!s}:SKIP:{name}:no_relevant_changed_paths")
            continue
        failures += _run_tool(name, config, [*scoped_args, *(_fix_args(name) if fix else [])]) != 0
    return 1 if failures else 0


def _fix_args(name: str) -> list[str]:
    if name == "ruff":
        return ["--fix"]
    if name == "biome":
        return ["--write"]
    return []


def _strip_separator(args: list[str]) -> list[str]:
    return args[1:] if args[:1] == ["--"] else args


def _normalize_explicit_args(root: Path, cwd: Path, args: list[str]) -> list[str]:
    normalized: list[str] = []
    cwd_resolved = cwd.resolve()
    for arg in args:
        if arg.startswith("-"):
            normalized.append(arg)
            continue
        candidate = (root / arg).resolve()
        if candidate.exists():
            normalized.append(
                candidate.relative_to(cwd_resolved).as_posix()
                if candidate.is_relative_to(cwd_resolved)
                else str(candidate)
            )
            continue
        normalized.append(arg)
    return normalized


def _extract_check_options(args: list[str]) -> tuple[list[str], bool, bool]:
    changed_only = False
    args = [
        arg
        for arg in args
        if not (arg in {"--changed-only", "-d"} and (changed_only := True))
    ]
    fix = "--fix" in args
    args = ["--fix"] if args == ["--fix"] else [arg for arg in args if arg != "--fix"]
    if changed_only and not args:
        args = ["--quick"]
    return args, changed_only, fix


def _run_named_tool(
    first: str,
    args: list[str],
    configs: dict[str, dict[str, Any]],
    *,
    changed_only: bool,
    fix: bool,
) -> int | None:
    if first not in configs:
        return None
    root = _repo_root()
    config = configs[first]
    cwd = _workdir(root, config)
    explicit_args = _normalize_explicit_args(root, cwd, _strip_separator(args[1:]))
    changed_files = _changed_files(root) if changed_only else []
    scoped_args = [] if explicit_args else _changed_args(
        first,
        root,
        cwd,
        config,
        changed_files,
    )
    if changed_only and config.get("pass_path") and not explicit_args and not scoped_args:
        label = config.get("label") or first.upper()
        print(f"{label!s}:SKIP:{first}:no_changed_paths")
        return 0
    if (
        changed_only
        and not config.get("pass_path")
        and not explicit_args
        and not _has_relevant_changed_files(first, changed_files)
    ):
        label = config.get("label") or first.upper()
        print(f"{label!s}:SKIP:{first}:no_relevant_changed_paths")
        return 0
    extra_args = [*explicit_args, *scoped_args, *(_fix_args(first) if fix else [])]
    return _run_tool(first, configs[first], extra_args)


def _selected_tools(
    first: str,
    configs: dict[str, dict[str, Any]],
) -> tuple[list[str], bool] | None:
    if first == "--fix":
        return [name for name in ("ruff", "biome") if name in configs], True
    if first in {"--check", "-c"}:
        return [name for name in ("ruff", "types", "pytest", "biome", "tsc", "vitest") if name in configs], False
    if first in {"--quick", "-q"}:
        return [name for name in ("ruff", "types", "pytest", "biome", "tsc") if name in configs], False
    if first in {"--frontend-only", "--fe"}:
        return [name for name in ("biome", "tsc", "vitest") if name in configs], False
    return None


def _usage(configs: dict[str, dict[str, Any]]) -> None:
    names = "|".join(sorted(configs))
    print(
        f"""Quality checks through st

Required path:
  Use st check for repo gates.
  Never run raw pytest, Vitest, Biome, TSC, Ruff, SQLFluff, Squawk, or legacy dt first.

Usage:
  st check --check
  st check --changed-only
  st check --quick [--changed-only]
  st check --frontend-only
  st check cleanroom -- <command>
  st check <{names}> [-- <tool args>]
"""
    )


@app.callback(invoke_without_command=True)
@usage(
    surface="st.check",
    cmd="st check --quick --changed-only",
    when="pre-edit gates; pre-commit; before reporting done",
    precautions=(
        "use st check for all quality gates (ruff/biome/tsc/types/pytest)",
        "never run raw pytest/vitest/biome/tsc/ruff/sqlfluff/squawk",
    ),
    tier="mandate",
)
def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands."""
    if ctx.invoked_subcommand is not None:
        return
    args = list(ctx.args)
    configs = _tool_configs()
    if not args or args[0] in {"-h", "--help", "help"}:
        _usage(configs)
        raise typer.Exit(0)

    args, changed_only, fix = _extract_check_options(args)
    first = args[0]
    if first == "cleanroom":
        raise typer.Exit(
            cleanroom_main(["--project-root", str(_repo_root()), *_strip_separator(args[1:])])
        )

    named_result = _run_named_tool(first, args, configs, changed_only=changed_only, fix=fix)
    if named_result is not None:
        raise typer.Exit(named_result)

    selected_result = _selected_tools(first, configs)
    if selected_result is None:
        output_error(f"Unknown st check mode/tool: {first}")
        raise typer.Exit(2)
    selected, selected_fix = selected_result

    raise typer.Exit(_run_selected(selected, configs, fix=fix or selected_fix, changed_only=changed_only))
