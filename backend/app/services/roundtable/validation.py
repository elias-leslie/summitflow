"""Path and parameter validation helpers for Roundtable tools.

Extracted from executor.py to provide reusable validation logic.
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.storage.projects import get_all_project_root_paths

# Cache TTL in seconds (5 minutes)
_CACHE_TTL = 300
_cache_timestamp: float = 0.0


def get_allowed_bases() -> list[str]:
    """Get allowed base directories from registered projects.

    Uses LRU cache with 5-minute TTL for performance.

    Returns:
        List of allowed base directory paths.
    """
    global _cache_timestamp
    current_time = time.time()

    # Invalidate cache if TTL expired
    if current_time - _cache_timestamp > _CACHE_TTL:
        _get_allowed_bases_cached.cache_clear()
        _cache_timestamp = current_time

    return _get_allowed_bases_cached()


@lru_cache(maxsize=1)
def _get_allowed_bases_cached() -> list[str]:
    """Internal cached function to fetch allowed bases."""
    return get_all_project_root_paths()


class ToolValidationResult:
    """Result from tool parameter validation operations.

    Used for validating tool inputs (paths, parameters, etc.)
    """

    def __init__(self, success: bool, value: str = "", error: str | None = None):
        self.success = success
        self.value = value
        self.error = error

    @property
    def failed(self) -> bool:
        return not self.success


# Alias for backward compatibility
ValidationResult = ToolValidationResult


def require_param(params: dict[str, Any], key: str) -> tuple[str, str | None]:
    """Extract a required parameter, returning error message if missing.

    Args:
        params: Parameters dictionary
        key: Required parameter key

    Returns:
        (value, None) on success, ("", error_message) on failure.
    """
    value = params.get(key, "")
    if not value:
        return "", f"{key} is required"
    return value, None


def validate_file_exists(
    path: Path, file_path: str, *, is_dir_error: str | None = None
) -> str | None:
    """Validate file exists and is a regular file.

    Args:
        path: Resolved Path object.
        file_path: Original file path string for error messages.
        is_dir_error: Custom error message if path is a directory. Defaults to "Not a file".

    Returns:
        None on success, error message on failure.
    """
    if not path.exists():
        return f"File not found: {file_path}"
    if not path.is_file():
        msg = is_dir_error or "Not a file"
        return f"{msg}: {file_path}"
    return None


def validate_path(
    path: str,
    default_base: str | None = None,
    allowed_paths: list[str] | None = None,
) -> tuple[bool, str]:
    """Validate that a path is within allowed directories.

    Handles both absolute and relative paths. Relative paths are resolved
    against the default_base (typically /home/kasadis/summitflow).

    Args:
        path: Path string to validate
        default_base: Default base directory for relative paths
        allowed_paths: Additional allowed path prefixes

    Returns:
        (is_valid, resolved_path or error_message)
    """
    try:
        path_obj = Path(path)

        # If relative path, try to resolve against allowed bases
        if not path_obj.is_absolute():
            # Try default base first
            if default_base:
                candidate = Path(default_base) / path
                if candidate.exists():
                    path_obj = candidate
                else:
                    # Try other allowed bases
                    for base in get_allowed_bases():
                        candidate = Path(base) / path
                        if candidate.exists():
                            path_obj = candidate
                            break
            else:
                # Try all allowed bases
                for base in get_allowed_bases():
                    candidate = Path(base) / path
                    if candidate.exists():
                        path_obj = candidate
                        break

        # Resolve to absolute path
        resolved = path_obj.resolve()
        resolved_str = str(resolved)

        # Check against allowed bases
        all_allowed = get_allowed_bases() + (allowed_paths or [])
        for base in all_allowed:
            if resolved_str.startswith(base):
                return True, resolved_str

        return False, f"Path not in allowed directories: {path}"
    except Exception as e:
        return False, f"Invalid path: {e}"


def require_valid_path(
    path: str,
    default_base: str | None = None,
    allowed_paths: list[str] | None = None,
) -> tuple[Path | None, str | None]:
    """Validate path and return Path object or error message.

    Convenience wrapper around validate_path that returns:
        (Path, None) on success - path is always valid
        (None, error_message) on failure

    Usage:
        path, err = require_valid_path(file_path)
        if err:
            return ToolResult(False, "", err)
        # Use path directly - guaranteed to be valid after err check

    Args:
        path: Path string to validate
        default_base: Default base directory for relative paths
        allowed_paths: Additional allowed path prefixes

    Returns:
        (Path, None) on success, (None, error_message) on failure
    """
    is_valid, result = validate_path(path, default_base, allowed_paths)
    if not is_valid:
        return None, result
    return Path(result), None
