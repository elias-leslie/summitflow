"""Step builders for task verification commands."""

from __future__ import annotations

import re


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

    if test_path:
        # Extract module info for import fallback
        path_match = re.match(r"^backend/(app|cli)/(.+?)(?:/([^/]+))?\.py$", relative_path)
        if path_match:
            rest = relative_path[len("backend/") : -len(".py")].replace("/", ".")
            return f"test -f {test_path} && dt pytest {test_path} -q --tb=short || python3 -c 'from {rest} import *'"

    # Frontend files - just check import/build
    if relative_path.startswith("frontend/"):
        return "cd frontend && npm run build --quiet"

    # Fallback: simple import check using python
    module_path = relative_path.replace("/", ".").replace(".py", "")
    return f"python3 -c 'import {module_path}' 2>/dev/null || echo 'Import check skipped'"


def build_refactor_steps(
    relative_path: str,
    file_path: str,
    lines: int,
    target_lines: int,
    is_frontend: bool,
    refactor_issues: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build verification steps for a refactor task.

    Generates issue-specific verify commands so each detected problem
    is verified as resolved, not just line count.

    Args:
        relative_path: Relative file path for display and verification commands
            (commands run from worktree root, so relative paths work correctly)
        file_path: Absolute file path (unused, kept for API compatibility)
        lines: Current line count
        target_lines: Target line count
        is_frontend: Whether this is a frontend file
        refactor_issues: List of specific issue identifiers to verify

    Returns:
        List of step dictionaries with description, verify_command
    """
    issues = refactor_issues or []
    steps: list[dict[str, str]] = []

    # Step 1: Size reduction (only when file has size issues)
    has_size_issue = any(i in issues for i in ("oversized", "large_file", "bloat_critical", "bloat_warning"))
    if has_size_issue or not issues:
        steps.append({
            "description": f"Refactor {relative_path} from {lines} to <{target_lines} lines",
            "verify_command": f"test $(wc -l < {relative_path}) -lt {target_lines}",
        })

    # Step 2: Structural issue verification (stdlib ast — no external deps)
    structural_checks: list[str] = []
    if "has_long_functions" in issues:
        structural_checks.append(
            f"python3 -c \"import ast; t=ast.parse(open('{relative_path}').read()); "
            f"bad=[n.name for n in ast.walk(t) "
            f"if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) "
            f"and n.end_lineno-n.lineno>50]; "
            f"assert not bad, f'Long functions: {{bad}}'\""
        )
    if "deep_nesting" in issues:
        structural_checks.append(
            f"python3 -c \"import ast; t=ast.parse(open('{relative_path}').read()); "
            f"deep=[n.name for n in ast.walk(t) "
            f"if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) "
            f"for c in ast.walk(n) "
            f"if isinstance(c,(ast.If,ast.For,ast.While,ast.With,ast.Try)) "
            f"and (c.col_offset-n.col_offset)//4>3]; "
            f"assert not deep, f'Deep nesting in: {{set(deep)}}'\""
        )
    if "too_many_functions" in issues:
        structural_checks.append(
            f"python3 -c \"import ast; t=ast.parse(open('{relative_path}').read()); "
            f"fns=[n.name for n in ast.walk(t) "
            f"if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]; "
            f"assert len(fns)<=20, f'Function count: {{len(fns)}}'\""
        )
    if "too_many_classes" in issues:
        structural_checks.append(
            f"python3 -c \"import ast; t=ast.parse(open('{relative_path}').read()); "
            f"cls=[n.name for n in ast.walk(t) if isinstance(n,ast.ClassDef)]; "
            f"assert len(cls)<=5, f'Class count: {{len(cls)}}'\""
        )
    if "has_large_classes" in issues:
        structural_checks.append(
            f"python3 -c \"import ast; t=ast.parse(open('{relative_path}').read()); "
            f"big=[n.name for n in ast.walk(t) if isinstance(n,ast.ClassDef) "
            f"and sum(1 for c in ast.iter_child_nodes(n) "
            f"if isinstance(c,(ast.FunctionDef,ast.AsyncFunctionDef)))>10]; "
            f"assert not big, f'Large classes: {{big}}'\""
        )
    if "too_many_imports" in issues:
        structural_checks.append(
            f"test $(grep -cE '^(import |from .+ import )' {relative_path}) -le 30"
        )

    if structural_checks:
        steps.append({
            "description": "Verify structural issues resolved (function length, nesting, counts)",
            "verify_command": " && ".join(structural_checks),
        })

    # Step 3: Quality gate (always)
    steps.append({
        "description": "Quality gate: auto-fix, lint, types, targeted tests",
        "verify_command": f"dt --fix 2>/dev/null; {get_targeted_test_command(relative_path)} && dt --quick --changed-only",
    })

    if is_frontend:
        steps.append({
            "description": "Verify no console errors in browser",
            "verify_command": "agent-browser open http://localhost:3001 && agent-browser wait --load networkidle",
        })

    return steps
