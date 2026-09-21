"""Changed-file detection and tool-relevance filtering for st check."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

from ..config import get_config_optional
from ..lib import leases
from .check_constants import _TOOL_CONFIG_PATHS, _TOOL_FILE_SUFFIXES


def _is_pytest_test_path(path: Path) -> bool:
    return path.suffix in {".py", ".pyi"} and (
        "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")
    )


def _python_module(rel_path: str) -> tuple[str, str] | None:
    path = Path(rel_path)
    if path.suffix not in {".py", ".pyi"} or _is_pytest_test_path(path):
        return None
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] == "backend":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return None
    return ".".join(parts), parts[-1]


def _test_imports(path: Path) -> tuple[set[str], set[tuple[str, str]]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return set(), set()
    imports: set[str] = set()
    from_imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            from_imports.update((node.module, alias.name) for alias in node.names)
    return imports, from_imports


def _test_imports_module(
    imports: set[str],
    from_imports: set[tuple[str, str]],
    module: str,
    leaf: str,
) -> bool:
    parent = module.rpartition(".")[0]
    return any(name == module or name.startswith(module + ".") for name in imports) or any(
        imported_from == module or (imported_from == parent and name == leaf)
        for imported_from, name in from_imports
    )


def _pytest_test_files(root: Path) -> list[Path]:
    roots = [root / "backend" / "tests", root / "tests"]
    packages = root / "packages"
    if packages.is_dir():
        roots.extend(path for path in packages.glob("*/tests") if path.is_dir())
    return sorted(
        path
        for test_root in roots
        if test_root.is_dir()
        for path in test_root.rglob("*.py")
        if _is_pytest_test_path(path.relative_to(root))
    )


def _focused_pytest_paths(root: Path, changed_files: list[str]) -> list[str] | None:
    tests = _pytest_test_files(root)
    imports_by_test: dict[Path, tuple[set[str], set[tuple[str, str]]]] | None = None
    selected: set[Path] = set()
    has_unmapped_implementation = False
    for rel_path in changed_files:
        path = Path(rel_path)
        if _is_pytest_test_path(path) and (root / path).is_file():
            selected.add((root / path).resolve())
            continue
        module = _python_module(rel_path)
        if module is None:
            continue
        dotted, leaf = module
        if imports_by_test is None:
            imports_by_test = {test: _test_imports(test) for test in tests}
        dependents = {
            test
            for test in tests
            if test.name in {f"test_{leaf}.py", f"{leaf}_test.py"}
            or test.name.startswith(f"test_{leaf}_")
            or _test_imports_module(*imports_by_test[test], dotted, leaf)
        }
        if not dependents:
            has_unmapped_implementation = True
            continue
        selected.update(dependents)
    if has_unmapped_implementation and not selected:
        return None
    return sorted(path.relative_to(root).as_posix() for path in selected)


def _lease_scope_enabled() -> bool:
    return os.environ.get("ST_CHECK_LEASE_SCOPE", "").strip().lower() in {"1", "true", "yes", "on"}


def _scope_to_leases(root: Path, changed: list[str]) -> list[str]:
    """Restrict changed files to paths the current agent has leased.

    In a shared checkout, parallel agents see each other's uncommitted churn via
    git, so one agent's `--changed-only` run fails on another agent's in-flight
    edits. With ST_CHECK_LEASE_SCOPE set, a scoped check considers only files the
    current agent leased. If the agent holds no leases, behaviour is unchanged
    (the full changed set) so this never silently narrows an unscoped run.
    """
    cfg = get_config_optional()
    pid = getattr(cfg, "project_id", "") if cfg else ""
    if not pid:
        return changed
    agent_id = leases.identify_agent()[0]
    mine = [lease for lease in leases.list_active(pid) if lease.agent_id == agent_id]
    if not mine:
        return changed
    return [
        rel
        for rel in changed
        if any(lease.matches(str((root / rel).resolve())) for lease in mine)
    ]


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
    changed = sorted(files)
    if _lease_scope_enabled():
        changed = _scope_to_leases(root, changed)
    return changed


def _changed_args(
    name: str,
    root: Path,
    cwd: Path,
    config: dict[str, object],
    changed_files: list[str],
) -> list[str]:
    if not changed_files or (name != "pytest" and not config.get("pass_path")):
        return []
    if name == "pytest":
        # Configuration, fixtures, and deletions can affect the whole suite.
        for rel_path in changed_files:
            path = Path(rel_path)
            if path.name in _TOOL_CONFIG_PATHS["pytest"]:
                return ["."]
            if path.suffix in _TOOL_FILE_SUFFIXES["pytest"] and (
                path.name == "conftest.py" or not (root / path).is_file()
            ):
                return ["."]
        focused = _focused_pytest_paths(root, changed_files)
        if focused is None:
            return []
        changed_files = focused
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
        return path.suffix in _TOOL_FILE_SUFFIXES.get(name, set())

    has_relevant = any(is_relevant(rel_path) for rel_path in changed_files)
    if name == "pytest" and has_relevant and not scoped_args:
        return "no_deterministic_focused_tests;run_targeted_pytest_or_full_acceptance"
    if config.get("pass_path"):
        if not scoped_args and not has_relevant:
            return "no_changed_paths"
        return None
    if not has_relevant:
        return "no_relevant_changed_paths"
    return None
