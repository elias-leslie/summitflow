"""Fix execution utilities for fix agent.

Handles file I/O and verification of fixes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)

_ST_CHECK_TYPES = frozenset({"ruff", "types", "biome", "tsc"})


def _build_verify_cmd(check_type: str, file_path: str) -> list[str] | None:
    """Return the command list for verifying a check type, or None if unknown."""
    st_cmd = shutil.which("st")
    if st_cmd and check_type in _ST_CHECK_TYPES:
        return [st_cmd, "check", check_type]
    fallbacks: dict[str, list[str]] = {
        "ruff": ["ruff", "check", file_path, "--quiet"],
        "types": ["ty", "check", file_path],
        "biome": ["npx", "biome", "check", file_path, "--quiet"],
        "tsc": ["npx", "tsc", "--noEmit"],
    }
    return fallbacks.get(check_type)


def read_file_content(file_path: Path, _context_lines: int = 10) -> str | None:
    """Read file content, returning None if the file is missing or unreadable."""
    if not file_path.exists():
        return None
    try:
        return file_path.read_text()
    except Exception as e:
        logger.warning("read_file_failed", path=str(file_path), error=str(e))
        return None


def apply_fix(file_path: Path, new_content: str) -> bool:
    """Write new_content to file_path, returning True on success."""
    try:
        file_path.write_text(new_content)
        return True
    except Exception as e:
        logger.error("apply_fix_failed", path=str(file_path), error=str(e))
        return False


def verify_fix(project_path: Path, check_type: str, file_path: str) -> bool:
    """Re-run the check to verify the fix worked.

    Uses st check for consistent tool execution. Falls back to raw tools
    only if st is not available.

    Args:
        project_path: Path to project root
        check_type: Type of check (ruff, types, biome, tsc)
        file_path: Path to the fixed file

    Returns:
        True if the check now passes
    """
    cmd = _build_verify_cmd(check_type, file_path)
    if cmd is None:
        logger.warning("unknown_check_type", check_type=check_type)
        return False
    try:
        result = subprocess.run(
            cmd, cwd=project_path, capture_output=True, text=True, timeout=60
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("verify_timeout", check_type=check_type, file=file_path)
        return False
    except Exception as e:
        logger.error("verify_failed", check_type=check_type, error=str(e))
        return False
