"""Tool discovery, resolution, and execution helpers for st check."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ..details import display_path, summary_hint, write_details
from ..tool_registry import load_tool_registry


def _resolve_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return Path.cwd()


def _tool_configs() -> dict[str, dict[str, object]]:
    registry = load_tool_registry()
    configs: dict[str, dict[str, object]] = {}
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


def _workdir(root: Path, config: dict[str, object]) -> Path:
    kind = str(config.get("working_dir") or "")
    backend = root / "backend"
    frontend = root / "frontend"
    candidates = {"backend": backend, "frontend": frontend}
    if kind in candidates and candidates[kind].exists():
        return candidates[kind]
    if kind == "migrations":
        return backend if (backend / "alembic").exists() else root
    if kind == "test" and backend.exists():
        return backend
    return root


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


def _run_tool(name: str, config: dict[str, object], extra_args: list[str]) -> int:
    root = _resolve_repo_root()
    cwd = _workdir(root, config)
    binary = str(config.get("binary") or name)
    base_args = shlex.split(str(config.get("args") or ""))
    if name == "biome" and any(not arg.startswith("-") for arg in extra_args):
        base_args = [arg for arg in base_args if arg != "."]
    if name == "pytest":
        has_path_arg = any(arg and not arg.startswith("-") for arg in extra_args)
        has_cov_control = any(arg == "--no-cov" or arg.startswith("--cov") for arg in extra_args)
        if has_path_arg and not has_cov_control:
            extra_args = ["--no-cov", *extra_args]
    command = [*_resolve_command(binary, root, cwd, base_args), *extra_args]
    label = str(config.get("label") or name.upper())
    print(f"{label}:{name}:start")

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

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
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
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    details = write_details(root, name, output)
    print(
        f"{label}:{'OK' if result.returncode == 0 else 'FAIL'}:{result.returncode}|"
        f"details:{display_path(root, details)}|hint:{summary_hint(output)}"
    )
    return result.returncode
