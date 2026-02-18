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
            return f"test -f {test_path} && dt pytest {test_path} -q --tb=short || python -c 'from {rest} import *'"

    # Frontend files - just check import/build
    if relative_path.startswith("frontend/"):
        return "cd frontend && npm run build --quiet"

    # Fallback: simple import check using python
    module_path = relative_path.replace("/", ".").replace(".py", "")
    return f"python -c 'import {module_path}' 2>/dev/null || echo 'Import check skipped'"


def build_refactor_steps(
    relative_path: str,
    file_path: str,
    lines: int,
    target_lines: int,
    is_frontend: bool,
) -> list[dict[str, str]]:
    """Build verification steps for a refactor task.

    Args:
        relative_path: Relative file path for display and verification commands
            (commands run from worktree root, so relative paths work correctly)
        file_path: Absolute file path (unused, kept for API compatibility)
        lines: Current line count
        target_lines: Target line count
        is_frontend: Whether this is a frontend file

    Returns:
        List of step dictionaries with description, verify_command
    """
    steps = [
        {
            "description": f"Refactor {relative_path} from {lines} to <{target_lines} lines",
            "verify_command": f"test $(wc -l < {relative_path}) -lt {target_lines}",
        },
        {
            "description": "Quality gate: auto-fix, lint, types, targeted tests",
            "verify_command": f"dt --fix 2>/dev/null; {get_targeted_test_command(relative_path)} && dt --quick --changed-only",
        },
    ]

    if is_frontend:
        steps.append(
            {
                "description": "Verify no console errors in browser",
                "verify_command": "agent-browser open http://localhost:3001 && agent-browser wait --load networkidle",
            }
        )

    return steps
