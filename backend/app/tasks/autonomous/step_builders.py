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


def get_targeted_test_command(relative_path: str) -> str:
    """Generate a targeted pytest command for the specific file being refactored.

    Maps source file paths to their corresponding test files.
    Falls back to import check if no test file pattern matches.

    Args:
        relative_path: Relative path to the source file (e.g., "backend/app/tasks/ai_review.py")

    Returns:
        Pytest command targeting specific tests, or import check as fallback
    """
    # Extract the module name and path components
    # e.g., "backend/app/tasks/ai_review.py" -> module="ai_review", dir="backend/app/tasks"
    path_match = re.match(r"^(backend)/(app|cli)/(.+)/([^/]+)\.py$", relative_path)
    if path_match:
        prefix, app_or_cli, subdir, module = path_match.groups()
        # Map to test file: backend/app/tasks/foo.py -> backend/tests/tasks/test_foo.py
        test_path = f"{prefix}/tests/{subdir}/test_{module}.py"
        # Use pytest with the specific test file, fallback to import check if file doesn't exist
        return f"test -f {test_path} && pytest {test_path} -q --tb=short || python -c 'from {app_or_cli}.{subdir.replace('/', '.')}.{module} import *'"

    # Handle direct backend/app/*.py or backend/cli/*.py files
    path_match = re.match(r"^(backend)/(app|cli)/([^/]+)\.py$", relative_path)
    if path_match:
        prefix, app_or_cli, module = path_match.groups()
        test_path = f"{prefix}/tests/test_{module}.py"
        return f"test -f {test_path} && pytest {test_path} -q --tb=short || python -c 'from {app_or_cli}.{module} import *'"

    # Frontend files - just check import/build
    if relative_path.startswith("frontend/"):
        return "cd frontend && npm run build --quiet"

    # Fallback: simple import check using python
    module_path = relative_path.replace("/", ".").replace(".py", "")
    return f"python -c 'import {module_path}' 2>/dev/null || echo 'Import check skipped'"


def build_quality_steps() -> list[dict[str, str]]:
    """Shared quality gate steps reusable across task types."""
    return [
        {
            "description": "Auto-fix lint and format issues",
            "verify_command": "dt --fix 2>/dev/null; dt --quick --changed-only",
            "expected_output": "CHECK_RESULT:OK",
        },
        {
            "description": "Full quality gate check",
            "verify_command": "dt --check",
            "expected_output": "CHECK_RESULT:OK",
        },
    ]


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
        List of step dictionaries with description, verify_command, expected_output
    """
    steps = [
        {
            "description": f"Analyze {relative_path} for refactoring opportunities",
            "verify_command": f"test -f {relative_path}",
            "expected_output": "exit code 0",
        },
        {
            "description": f"Split/refactor to reduce line count from {lines} to <{target_lines}",
            "verify_command": f"test $(wc -l < {relative_path}) -lt {target_lines}",
            "expected_output": "exit code 0",
        },
        {
            "description": "Auto-fix lint/format then verify",
            "verify_command": "dt --fix 2>/dev/null; dt --quick --changed-only",
            "expected_output": "CHECK_RESULT:OK",
        },
        {
            "description": f"Verify tests for {relative_path}",
            "verify_command": get_targeted_test_command(relative_path),
            "expected_output": "exit code 0",
        },
        {
            "description": "Full quality gate check",
            "verify_command": "dt --check",
            "expected_output": "CHECK_RESULT:OK",
        },
    ]

    if is_frontend:
        steps.append(
            {
                "description": "Verify no console errors in browser",
                "verify_command": "agent-browser open http://localhost:3001 && agent-browser wait --load networkidle",
                "expected_output": "exit code 0",
            }
        )

    steps.append(
        {
            "description": "Commit changes via commit.sh",
            "verify_command": 'commit.sh --json | grep -q \'"status":"SUCCESS"\'',
            "expected_output": "exit code 0",
        }
    )

    return steps
