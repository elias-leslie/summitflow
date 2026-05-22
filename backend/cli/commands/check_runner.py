"""Tool discovery and working-directory helpers for st check.

Tool *execution* (`_run_tool`) and binary *resolution* (`_resolve_command`)
live in ``check.py`` so the test suite can patch their dependencies
(``subprocess``, ``shutil``, ``_resolve_repo_root``) on the ``cli.commands.check``
namespace where they execute.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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
