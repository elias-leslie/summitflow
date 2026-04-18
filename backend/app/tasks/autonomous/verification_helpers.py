"""Helper utilities for step verification.

Provides command expansion, output parsing, and file detection utilities.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)

# Regex patterns for .venv path stripping.
# Matches: .venv/bin/X, backend/.venv/bin/X
_VENV_BIN_PATTERN = re.compile(r"(?:backend/)?\.venv/bin/")
# Matches: source .venv/bin/activate &&, source backend/.venv/bin/activate &&
# Also: . .venv/bin/activate &&
_SOURCE_ACTIVATE_PATTERN = re.compile(
    r"(?:source|\.)\s+(?:backend/)?\.venv/bin/activate\s*&&\s*"
)


def strip_venv_paths(cmd: str) -> str:
    """Strip .venv/bin/ prefixes from commands.

    Since build_project_env() puts the correct venv on PATH, relative
    .venv/bin/X paths are unnecessary and fail in sibling checkouts where .venv
    doesn't exist. This rewrites them to bare binary names.

    Handles:
        .venv/bin/ruff check app/     -> ruff check app/
        backend/.venv/bin/pytest ...  -> pytest ...
        cd backend && .venv/bin/ty  -> cd backend && ty
        source .venv/bin/activate &&  -> (removed entirely)
    """
    if ".venv" not in cmd:
        return cmd

    # First remove "source .venv/bin/activate &&" patterns
    cmd = _SOURCE_ACTIVATE_PATTERN.sub("", cmd)

    # Then strip .venv/bin/ and backend/.venv/bin/ prefixes
    cmd = _VENV_BIN_PATTERN.sub("", cmd)

    return cmd


def expand_command(cmd: str) -> str:
    """Expand command aliases and strip .venv paths."""
    # Always strip .venv paths — venv is on PATH via build_project_env()
    return strip_venv_paths(cmd)


def get_diff_range(project_path: str, base_branch: str = "main") -> str:
    """Return a git diff range from merge-base to HEAD, with a safe fallback."""
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", "HEAD", base_branch],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if merge_base.returncode == 0 and merge_base.stdout.strip():
            return f"{merge_base.stdout.strip()}..HEAD"
    except Exception:
        logger.debug("merge_base_lookup_failed", exc_info=True)
    return "HEAD~1..HEAD"


def detect_changed_files(project_path: str) -> list[str]:
    """Detect Python files changed in the last commit.

    Uses the merge-base against main to find files modified by the agent.

    Returns:
        List of changed .py file paths relative to project root.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", get_diff_range(project_path), "--", "*.py"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("git_diff_failed", stderr=result.stderr[:200])
            return []

        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        logger.info("smoke_test_files_detected", count=len(files), files=files[:10])
        return files
    except Exception as e:
        logger.warning("smoke_test_detect_error", error=str(e))
        return []


def file_to_module(project_path: str, file_path: str) -> str | None:
    """Convert file path to Python module name.

    Args:
        project_path: Root path of the project
        file_path: Relative path like 'backend/cli/output.py'

    Returns:
        Module name like 'cli.output' or None if not importable.
    """
    if not file_path.endswith(".py"):
        return None
    file_path = file_path[:-12] if file_path.endswith("__init__.py") else file_path[:-3]

    # Handle backend/ prefix - strip it for module path
    if file_path.startswith("backend/"):
        file_path = file_path[8:]

    # Handle app/ prefix - keep it for summitflow backend structure
    # Convert path separators to dots
    module_name = file_path.replace("/", ".").replace("\\", ".")

    # Skip test files, migrations, and alembic versions
    lower = module_name.lower()
    if "test" in lower or "migration" in lower or "alembic" in lower:
        return None

    # Skip files with hyphens — not valid Python identifiers; `import a-b`
    # is always a SyntaxError (parsed as subtraction).
    if "-" in module_name:
        return None

    return module_name if module_name else None


def resolve_working_directory(working_dir: str, command: str) -> str:
    """Resolve the effective working directory for a command.

    For pytest or python commands targeting backend, use backend/ as cwd.

    Args:
        working_dir: Base working directory
        command: Command to execute

    Returns:
        Effective working directory path
    """
    backend_dir = str(Path(working_dir) / "backend")
    if Path(backend_dir).is_dir() and (
        "pytest backend/" in command or "python -c" in command
    ):
        return backend_dir
    return working_dir


def adjust_command_for_cwd(command: str, original_cwd: str, new_cwd: str) -> str:
    """Adjust command paths when changing working directory.

    Args:
        command: Original command
        original_cwd: Original working directory
        new_cwd: New working directory

    Returns:
        Adjusted command with corrected paths
    """
    if new_cwd.endswith("/backend") and original_cwd != new_cwd:
        return command.replace("backend/tests/", "tests/")
    return command
