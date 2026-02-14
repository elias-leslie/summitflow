"""Fix execution utilities for fix agent.

Handles file I/O and verification of fixes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)


def read_file_content(file_path: Path, _context_lines: int = 10) -> str | None:
    """Read file content with surrounding context.

    Args:
        file_path: Path to file
        context_lines: Number of lines of context to include around error

    Returns:
        File content or None if file doesn't exist
    """
    if not file_path.exists():
        return None
    try:
        return file_path.read_text()
    except Exception as e:
        logger.warning("read_file_failed", path=str(file_path), error=str(e))
        return None


def apply_fix(file_path: Path, new_content: str) -> bool:
    """Apply the fix to the file.

    Args:
        file_path: Path to file
        new_content: New file content

    Returns:
        True if fix was applied successfully
    """
    try:
        file_path.write_text(new_content)
        return True
    except Exception as e:
        logger.error("apply_fix_failed", path=str(file_path), error=str(e))
        return False


def verify_fix(
    project_path: Path,
    check_type: str,
    file_path: str,
) -> bool:
    """Re-run the check to verify the fix worked.

    Uses dt wrapper for consistent tool execution. Falls back to raw tools
    only if dt is not available.

    Args:
        project_path: Path to project root
        check_type: Type of check (ruff, mypy, biome, tsc)
        file_path: Path to the fixed file

    Returns:
        True if the check now passes
    """
    import shutil

    dt_cmd = shutil.which("dt")

    if dt_cmd and check_type in ("ruff", "mypy", "biome", "tsc"):
        # Use dt for verification — consistent with quality gate pipeline
        cmd = [dt_cmd, check_type]
    elif check_type == "ruff":
        cmd = ["ruff", "check", file_path, "--quiet"]
    elif check_type == "mypy":
        cmd = ["mypy", file_path, "--no-error-summary", "--quiet"]
    elif check_type == "biome":
        cmd = ["npx", "biome", "check", file_path, "--quiet"]
    elif check_type == "tsc":
        cmd = ["npx", "tsc", "--noEmit"]
    else:
        logger.warning("unknown_check_type", check_type=check_type)
        return False

    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("verify_timeout", check_type=check_type, file=file_path)
        return False
    except Exception as e:
        logger.error("verify_failed", check_type=check_type, error=str(e))
        return False
