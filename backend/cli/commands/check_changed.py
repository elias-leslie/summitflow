"""Changed-file detection and tool-relevance filtering for st check."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .check_constants import _TOOL_CONFIG_PATHS, _TOOL_FILE_SUFFIXES


def _is_pytest_test_path(path: Path) -> bool:
    return path.suffix in {".py", ".pyi"} and (
        "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")
    )


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


def _changed_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, object],
    changed_files: list[str],
) -> list[str]:
    if not changed_files or (name != "pytest" and not config.get("pass_path")):
        return []
    paths: list[str] = []
    cwd_resolved = cwd.resolve()
    for rel_path in changed_files:
        if Path(rel_path).name in _TOOL_CONFIG_PATHS.get(name, set()):
            continue
        absolute = (root / rel_path).resolve()
        if not absolute.exists() or not absolute.is_file():
            continue
        if name == "pytest":
            path = Path(rel_path)
            if not _is_pytest_test_path(path):
                continue
            if absolute.name == "conftest.py":
                absolute = absolute.parent
        if not absolute.is_relative_to(cwd_resolved):
            continue
        relative = absolute.relative_to(cwd)
        if name in {"ruff", "types"} and relative.suffix not in {".py", ".pyi"}:
            continue
        if name in {"sqlfluff", "squawk"} and relative.suffix != ".sql":
            continue
        rel_posix = relative.as_posix()
        if rel_posix not in paths:
            paths.append(rel_posix)
    return paths


def _skip_reason(
    name: str,
    config: dict[str, object],
    *,
    changed_only: bool,
    changed_files: list[str],
    scoped_args: list[str],
    explicit_args: bool = False,
) -> str | None:
    if not changed_only or explicit_args:
        return None

    def is_relevant(rel_path: str) -> bool:
        path = Path(rel_path)
        if path.name in _TOOL_CONFIG_PATHS.get(name, set()):
            return True
        if name == "pytest":
            return _is_pytest_test_path(path)
        return path.suffix in _TOOL_FILE_SUFFIXES.get(name, set())

    has_relevant = any(is_relevant(rel_path) for rel_path in changed_files)
    if config.get("pass_path"):
        if not scoped_args and not has_relevant:
            return "no_changed_paths"
        return None
    if not has_relevant:
        return "no_relevant_changed_paths"
    return None
