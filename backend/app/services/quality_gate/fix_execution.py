"""Fix execution utilities for fix agent.

Handles file I/O and verification of fixes.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ...logging_config import get_logger
from ...utils import safe_subprocess

logger = get_logger(__name__)

_ST_CHECK_TYPES = frozenset({"ruff", "types", "biome", "tsc"})


@dataclass(frozen=True)
class FileMutationSnapshot:
    """Original on-disk state used to roll back an attempted generated fix."""

    existed: bool
    content: bytes


def capture_file_snapshot(file_path: Path) -> FileMutationSnapshot:
    """Capture exact file bytes before an auto-fix mutation."""
    if not file_path.exists():
        return FileMutationSnapshot(existed=False, content=b"")
    if not file_path.is_file():
        raise ValueError(f"Fix target is not a regular file: {file_path}")
    return FileMutationSnapshot(existed=True, content=file_path.read_bytes())


def restore_file_snapshot(
    file_path: Path,
    snapshot: FileMutationSnapshot,
    *,
    expected_current: bytes | None = None,
) -> bool:
    """Restore a captured state unless another writer changed the fix target."""
    try:
        if expected_current is not None:
            try:
                current = file_path.read_bytes()
            except FileNotFoundError:
                current = None
            if current != expected_current:
                logger.warning(
                    "fix_rollback_skipped_concurrent_change",
                    path=str(file_path),
                )
                return False
        if snapshot.existed:
            file_path.write_bytes(snapshot.content)
        else:
            file_path.unlink(missing_ok=True)
        return True
    except OSError as exc:
        logger.error("fix_rollback_failed", path=str(file_path), error=str(exc))
        return False


def _build_verify_cmd(check_type: str, file_path: str) -> list[str] | None:
    """Return the command list for verifying a check type, or None if unknown."""
    st_cmd = shutil.which("st")
    if not st_cmd or check_type not in _ST_CHECK_TYPES:
        return None
    return [st_cmd, "check", check_type]


def read_file_content(file_path: Path, _context_lines: int = 10) -> str | None:
    """Read file content, returning None if the file is missing or unreadable."""
    if not file_path.exists():
        return None
    try:
        return file_path.read_text()
    except Exception as e:
        logger.warning("read_file_failed", path=str(file_path), error=str(e))
        return None


def apply_fix(
    file_path: Path,
    new_content: str,
    *,
    expected_current: bytes | None = None,
) -> bool:
    """Write a fix only while the target still matches the prompted content."""
    try:
        if expected_current is not None:
            try:
                current = file_path.read_bytes()
            except FileNotFoundError:
                current = None
            if current != expected_current:
                logger.warning(
                    "fix_apply_skipped_concurrent_change",
                    path=str(file_path),
                )
                return False
        file_path.write_text(new_content, encoding="utf-8")
        return True
    except Exception as e:
        logger.error("apply_fix_failed", path=str(file_path), error=str(e))
        return False


def verify_fix(project_path: Path, check_type: str, file_path: str) -> bool:
    """Re-run the check to verify the fix worked.

    Uses st check for consistent tool execution. Verification fails closed when
    the canonical tool surface is unavailable.

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
        result = safe_subprocess.run(
            cmd, cwd=project_path, capture_output=True, text=True, timeout=60
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("verify_timeout", check_type=check_type, file=file_path)
        return False
    except Exception as e:
        logger.error("verify_failed", check_type=check_type, error=str(e))
        return False
