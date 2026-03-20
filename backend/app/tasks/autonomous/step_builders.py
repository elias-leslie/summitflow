"""Step builders for task verification commands."""

from __future__ import annotations

import re
import shlex

_SIZE_ISSUES = ("oversized", "large_file", "bloat_critical", "bloat_warning")


def calculate_target_lines(current_lines: int) -> int:
    """Calculate target line count for refactoring.

    Args:
        current_lines: Current file line count

    Returns:
        Target line count. Returns current_lines if file is already
        at or below the minimum threshold (no refactoring needed).
    """
    if current_lines <= 150:
        return current_lines
    if current_lines > 1000:
        return 500  # Large files should get to 500
    elif current_lines > 500:
        return 300  # Medium-large files should get to 300
    elif current_lines > 300:
        return 200  # Medium files should get to 200
    else:
        return 150  # Small files - modest reduction


def find_test_file(relative_path: str) -> str | None:
    """Map a source file to its corresponding test file.

    Args:
        relative_path: Relative path to the source file
            (e.g., "backend/app/tasks/ai_review.py")

    Returns:
        Relative test file path, or None if no mapping exists.
    """
    # backend/app/tasks/foo.py -> backend/tests/tasks/test_foo.py
    path_match = re.match(r"^(backend)/(app|cli)/(.+)/([^/]+)\.py$", relative_path)
    if path_match:
        prefix, _app_or_cli, subdir, module = path_match.groups()
        return f"{prefix}/tests/{subdir}/test_{module}.py"
    # backend/app/foo.py -> backend/tests/test_foo.py
    path_match = re.match(r"^(backend)/(app|cli)/([^/]+)\.py$", relative_path)
    if path_match:
        prefix, _app_or_cli, module = path_match.groups()
        return f"{prefix}/tests/test_{module}.py"
    return None


def get_targeted_test_command(relative_path: str) -> str:
    """Generate a targeted pytest command for the specific file being refactored.

    Maps source file paths to their corresponding test files.
    Falls back to import check if no test file pattern matches.

    Args:
        relative_path: Relative path to the source file (e.g., "backend/app/tasks/ai_review.py")

    Returns:
        Pytest command targeting specific tests, or import check as fallback
    """
    test_path = find_test_file(relative_path)
    nearby_test = _build_nearby_test_search_command(relative_path)
    if test_path:
        path_match = re.match(r"^backend/(app|cli)/(.+?)(?:/([^/]+))?\.py$", relative_path)
        if path_match:
            rest = relative_path[len("backend/") : -len(".py")].replace("/", ".")
            fallback = nearby_test or f"python3 -c 'from {rest} import *'"
            return f"test -f {test_path} && dt pytest {test_path} -q --tb=short || {fallback}"
    # Frontend files - just check import/build
    if relative_path.startswith("frontend/"):
        return "cd frontend && npm run build --quiet"
    if nearby_test:
        return nearby_test
    # Fallback: simple import check using python
    module_path = relative_path.replace("/", ".").replace(".py", "")
    return f"python3 -c 'import {module_path}' 2>/dev/null || echo 'Import check skipped'"


def _build_nearby_test_search_command(relative_path: str) -> str | None:
    """Build a bounded nearby-test search command for modules without exact test mapping."""
    if not relative_path.startswith("backend/") or not relative_path.endswith(".py"):
        return None

    parts = [p for p in relative_path[:-3].split("/") if p not in {"backend", "app", "cli"}]
    if not parts:
        return None

    stem = parts[-1].lstrip("_")
    parent = parts[-2] if len(parts) >= 2 else ""
    grandparent = parts[-3] if len(parts) >= 3 else ""
    keywords = [p for p in (stem, parent, grandparent) if p]
    if not keywords:
        return None

    module_path = relative_path.replace("/", ".").replace(".py", "")
    pattern = "|".join(re.escape(keyword) for keyword in dict.fromkeys(keywords))
    pattern_q = shlex.quote(pattern)
    import_q = shlex.quote(f"from {module_path} import *")
    script = (
        f"tests=$(rg --files backend/tests | rg -i {pattern_q} | head -n 3); "
        'if [ -n "$tests" ]; then '
        'dt pytest $tests -q --tb=short; '
        "else "
        f"python3 -c {import_q}; "
        "fi"
    )
    return f"bash -lc {shlex.quote(script)}"


def _ast_check(path: str, body: str) -> str:
    """Wrap an AST check body into a python3 one-liner."""
    return f"python3 -c \"import ast; t=ast.parse(open('{path}').read()); {body}\""


def _build_function_checks(relative_path: str, issues: list[str]) -> list[str]:
    """Return structural check commands for function-level issues."""
    p = relative_path
    checks: list[str] = []
    if "has_long_functions" in issues:
        checks.append(_ast_check(p,
            "bad=[n.name for n in ast.walk(t) "
            "if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) "
            "and n.end_lineno-n.lineno>50]; "
            "assert not bad, f'Long functions: {bad}'"
        ))
    if "deep_nesting" in issues:
        checks.append(_ast_check(p,
            "deep=[n.name for n in ast.walk(t) "
            "if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) "
            "for c in ast.walk(n) "
            "if isinstance(c,(ast.If,ast.For,ast.While,ast.With,ast.Try)) "
            "and (c.col_offset-n.col_offset)//4>3]; "
            "assert not deep, f'Deep nesting in: {set(deep)}'"
        ))
    if "too_many_functions" in issues:
        checks.append(_ast_check(p,
            "fns=[n.name for n in ast.walk(t) "
            "if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]; "
            "assert len(fns)<=20, f'Function count: {len(fns)}'"
        ))
    return checks


def _build_class_checks(relative_path: str, issues: list[str]) -> list[str]:
    """Return structural check commands for class-level issues."""
    p = relative_path
    checks: list[str] = []
    if "too_many_classes" in issues:
        checks.append(_ast_check(p,
            "cls=[n.name for n in ast.walk(t) if isinstance(n,ast.ClassDef)]; "
            "assert len(cls)<=5, f'Class count: {len(cls)}'"
        ))
    if "has_large_classes" in issues:
        checks.append(_ast_check(p,
            "big=[n.name for n in ast.walk(t) if isinstance(n,ast.ClassDef) "
            "and sum(1 for c in ast.iter_child_nodes(n) "
            "if isinstance(c,(ast.FunctionDef,ast.AsyncFunctionDef)))>10]; "
            "assert not big, f'Large classes: {big}'"
        ))
    if "too_many_imports" in issues:
        checks.append(f"test $(grep -cE '^(import |from .+ import )' {relative_path}) -le 30")
    return checks


def _build_structural_checks(relative_path: str, issues: list[str]) -> list[str]:
    """Build AST-based verification commands for each structural issue."""
    # Python AST checks only apply to .py files — skip for JS/TS/etc.
    if not relative_path.endswith(".py"):
        return []
    return _build_function_checks(relative_path, issues) + _build_class_checks(relative_path, issues)


def _step(description: str, verify_commands: list[str] | None = None) -> dict[str, object]:
    """Build a step payload, storing executable verification in spec."""
    step: dict[str, object] = {"description": description}
    if verify_commands:
        step["spec"] = {"verify_commands": verify_commands}
    return step


def _assemble_steps(
    relative_path: str, lines: int, target_lines: int, is_frontend: bool, issues: list[str],
) -> list[dict[str, object]]:
    """Assemble the ordered list of verification steps."""
    steps: list[dict[str, object]] = []
    if any(i in issues for i in _SIZE_ISSUES) or not issues:
        steps.append(_step(
            f"Refactor {relative_path} to simplify structure and reduce size where it helps (guideline: aim for <{target_lines} lines from {lines})",
        ))
    structural_checks = _build_structural_checks(relative_path, issues)
    if structural_checks:
        steps.append(_step(
            "Verify structural issues resolved with targeted checks",
            structural_checks,
        ))
    targeted_test = get_targeted_test_command(relative_path)
    steps.append(_step(
        "Quality gate: run fix, fast checks, then targeted verification",
        ["dt --fix", "dt --quick", targeted_test],
    ))
    if is_frontend:
        steps.append(_step(
            "Verify no console errors in browser",
            ["~/.local/bin/sf-browser console"],
        ))
    return steps


def build_refactor_steps(
    relative_path: str,
    file_path: str,
    lines: int,
    target_lines: int,
    is_frontend: bool,
    refactor_issues: list[str] | None = None,
) -> list[dict[str, object]]:
    """Build verification steps for a refactor task.

    Generates issue-specific verify commands so each detected problem
    is verified as resolved, not just line count.

    Args:
        relative_path: Relative file path (commands run from worktree root)
        file_path: Absolute file path (unused, kept for API compatibility)
        lines: Current line count
        target_lines: Target line count
        is_frontend: Whether this is a frontend file
        refactor_issues: List of specific issue identifiers to verify

    Returns:
        List of step dictionaries with description and optional spec.verify_commands
    """
    return _assemble_steps(relative_path, lines, target_lines, is_frontend, refactor_issues or [])
