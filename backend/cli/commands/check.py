"""Canonical quality-check command surface."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import typer

from ..lib.cleanroom import main as cleanroom_main
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

app = typer.Typer(
    help="Quality checks through the managed st surface.",
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
    if not changed_files or not config.get("pass_path"):
        return []
    paths: list[str] = []
    for rel_path in changed_files:
        absolute = (root / rel_path).resolve()
        if not absolute.exists() or not absolute.is_file():
            continue
        if absolute.is_relative_to(cwd.resolve()):
            relative = absolute.relative_to(cwd)
            if _path_allowed_for_tool(name, relative):
                paths.append(relative.as_posix())
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
    command = [*_resolve_command(binary, root, cwd, base_args), *extra_args]
    label = str(config.get("label") or name.upper())
    print(f"{label}:{name}:start")
    result = subprocess.run(command, cwd=cwd, env=_env(root), check=False)
    print(f"{label}:{'OK' if result.returncode == 0 else 'FAIL'}:{result.returncode}")
    return result.returncode


def _run_selected(
    selected: list[str],
    configs: dict[str, dict[str, Any]],
    *,
    fix: bool,
    changed_only: bool,
) -> int:
    root = _repo_root()
    changed_files = _changed_files(root) if changed_only else []
    failures = 0
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
        failures += (
            _run_tool(name, config, [*scoped_args, *(_fix_args(name) if fix else [])]) != 0
        )
    return 1 if failures else 0


def _fix_args(name: str) -> list[str]:
    if name == "ruff":
        return ["--fix"]
    if name == "biome":
        return ["--write"]
    return []


def _strip_separator(args: list[str]) -> list[str]:
    return args[1:] if args[:1] == ["--"] else args


def _usage(configs: dict[str, dict[str, Any]]) -> None:
    names = "|".join(sorted(configs))
    print(
        f"""Quality checks through st

Usage:
  st check --check
  st check --quick [--changed-only]
  st check --frontend-only
  st check cleanroom -- <command>
  st check <{names}> [-- <tool args>]
"""
    )


@app.callback(invoke_without_command=True)
def check(ctx: typer.Context) -> None:
    """Run quality gates or named check subcommands."""
    if ctx.invoked_subcommand is not None:
        return
    args = list(ctx.args)
    configs = _tool_configs()
    if not args or args[0] in {"-h", "--help", "help"}:
        _usage(configs)
        raise typer.Exit(0)

    changed_only = False
    args = [
        arg
        for arg in args
        if not (arg in {"--changed-only", "-d"} and (changed_only := True))
    ]
    fix = "--fix" in args
    args = ["--fix"] if args == ["--fix"] else [arg for arg in args if arg != "--fix"]

    first = args[0]
    if first == "cleanroom":
        raise typer.Exit(
            cleanroom_main(["--project-root", str(_repo_root()), *_strip_separator(args[1:])])
        )

    if first in configs:
        root = _repo_root()
        config = configs[first]
        cwd = _workdir(root, config)
        explicit_args = _strip_separator(args[1:])
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
            raise typer.Exit(0)
        if (
            changed_only
            and not config.get("pass_path")
            and not explicit_args
            and not _has_relevant_changed_files(first, changed_files)
        ):
            label = config.get("label") or first.upper()
            print(f"{label!s}:SKIP:{first}:no_relevant_changed_paths")
            raise typer.Exit(0)
        extra_args = [*explicit_args, *scoped_args, *(_fix_args(first) if fix else [])]
        raise typer.Exit(_run_tool(first, configs[first], extra_args))

    if first == "--fix":
        selected = [name for name in ("ruff", "biome") if name in configs]
        fix = True
    elif first in {"--check", "-c"}:
        selected = [name for name in ("ruff", "types", "pytest", "biome", "tsc", "vitest") if name in configs]
    elif first in {"--quick", "-q"}:
        selected = [name for name in ("ruff", "types", "pytest", "biome", "tsc") if name in configs]
    elif first in {"--frontend-only", "--fe"}:
        selected = [name for name in ("biome", "tsc", "vitest") if name in configs]
    else:
        output_error(f"Unknown st check mode/tool: {first}")
        raise typer.Exit(2)

    raise typer.Exit(_run_selected(selected, configs, fix=fix, changed_only=changed_only))
