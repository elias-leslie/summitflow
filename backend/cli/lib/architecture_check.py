"""Architecture checks used by st check."""

from __future__ import annotations

import ast
import contextlib
from pathlib import Path

from ..details import display_path, summary_hint, write_details

_ARCH_CHECK_DIRS = (
    Path("backend/app/api"),
    Path("backend/app/services"),
    Path("backend/app/utils"),
)
_ARCH_ALLOWLIST = {
    Path("backend/app/utils/safe_subprocess.py"),
}
_SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}
_ASYNC_SUBPROCESS_CALLS = {"create_subprocess_exec", "create_subprocess_shell"}


def run_architecture_check(root: Path, changed_files: list[str] | None) -> int:
    paths = _architecture_paths(root, changed_files)
    if changed_files is not None and not paths:
        print("ARCH:SKIP:architecture:no_changed_paths")
        return 0
    violations = _unsafe_subprocess_violations(root, paths)
    output = "\n".join(violations)
    details = write_details(root, "architecture", output)
    if violations:
        print(
            f"ARCH:FAIL:1|details:{display_path(root, details)}|"
            f"hint:{summary_hint(output)}"
        )
        return 1
    print(f"ARCH:OK:architecture|details:{display_path(root, details)}")
    return 0


def _architecture_paths(root: Path, changed_files: list[str] | None) -> list[Path]:
    if changed_files is not None:
        candidates = [root / rel_path for rel_path in changed_files]
    else:
        candidates = [
            path
            for base in _ARCH_CHECK_DIRS
            for path in (root / base).rglob("*.py")
        ]
    paths: list[Path] = []
    for candidate in candidates:
        with contextlib.suppress(OSError, ValueError):
            rel = candidate.resolve().relative_to(root.resolve())
            if (
                candidate.is_file()
                and candidate.suffix == ".py"
                and rel not in _ARCH_ALLOWLIST
                and any(rel.is_relative_to(base) for base in _ARCH_CHECK_DIRS)
            ):
                paths.append(candidate)
    return sorted(set(paths))


def _unsafe_subprocess_violations(root: Path, paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        rel_path = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
        except (OSError, SyntaxError) as exc:
            violations.append(f"{rel_path}:1 cannot scan architecture gate: {exc}")
            continue
        violations.extend(_unsafe_subprocess_calls(rel_path, tree))
    return violations


def _unsafe_subprocess_calls(rel_path: str, tree: ast.AST) -> list[str]:
    subprocess_names = {"subprocess"}
    asyncio_names = {"asyncio"}
    banned_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                if alias.name == "subprocess":
                    subprocess_names.add(name)
                elif alias.name == "asyncio":
                    asyncio_names.add(name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                for alias in node.names:
                    if alias.name in _SUBPROCESS_CALLS:
                        banned_names[alias.asname or alias.name] = alias.name
            elif node.module == "asyncio":
                for alias in node.names:
                    if alias.name in _ASYNC_SUBPROCESS_CALLS:
                        banned_names[alias.asname or alias.name] = alias.name

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _banned_call_name(node.func, subprocess_names, asyncio_names, banned_names)
        if name:
            violations.append(
                f"{rel_path}:{node.lineno} raw {name} in web app code; "
                "use app.utils.safe_subprocess or os.posix_spawn"
            )
    return violations


def _banned_call_name(
    func: ast.expr,
    subprocess_names: set[str],
    asyncio_names: set[str],
    banned_names: dict[str, str],
) -> str | None:
    if isinstance(func, ast.Name):
        return banned_names.get(func.id)
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr in _SUBPROCESS_CALLS and isinstance(func.value, ast.Name) and func.value.id in subprocess_names:
        return f"subprocess.{func.attr}"
    if func.attr in _ASYNC_SUBPROCESS_CALLS and isinstance(func.value, ast.Name) and func.value.id in asyncio_names:
        return f"asyncio.{func.attr}"
    return None
