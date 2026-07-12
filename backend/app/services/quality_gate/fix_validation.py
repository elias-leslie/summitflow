"""Validation utilities for fix agent.

Handles precondition checks before attempting fixes.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path

logger = get_logger(__name__)

_REPOSITORY_CONTROL_DIRECTORIES = frozenset({".git", ".jj"})

# Supported check types for automatic fixing
SUPPORTED_CHECK_TYPES = ("ruff", "types", "biome", "tsc")


def resolve_repo_contained_path(project_path: Path, untrusted_path: str) -> Path:
    """Resolve an untrusted relative file path inside a project repository.

    Quality-check paths and model-generated fix targets are both untrusted.  In
    particular, resolving ``root / path`` alone is not sufficient because an
    absolute path discards ``root`` and a repository symlink can point outside
    it.  Reject those inputs before returning a canonical path.

    Raises:
        ValueError: If the path is empty, absolute, contains traversal, or
            resolves outside the project root (including through a symlink).
    """
    if not isinstance(untrusted_path, str) or not untrusted_path or "\x00" in untrusted_path:
        raise ValueError("File path must be a non-empty relative path")

    candidate = Path(untrusted_path)
    windows_candidate = PureWindowsPath(untrusted_path)
    if (
        candidate.is_absolute()
        or windows_candidate.is_absolute()
        or bool(windows_candidate.drive)
        or bool(windows_candidate.root)
    ):
        raise ValueError("Absolute file paths are not allowed")
    if ".." in candidate.parts or ".." in windows_candidate.parts:
        raise ValueError("Parent path traversal is not allowed")
    if _REPOSITORY_CONTROL_DIRECTORIES.intersection(
        {*candidate.parts, *windows_candidate.parts}
    ):
        raise ValueError("Repository control paths are not allowed")

    try:
        root = project_path.resolve()
        target = (root / candidate).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("File path could not be resolved safely") from exc
    if target == root or not target.is_relative_to(root):
        raise ValueError("File path must resolve inside the project repository")
    if _REPOSITORY_CONTROL_DIRECTORIES.intersection(target.relative_to(root).parts):
        raise ValueError("Repository control paths are not allowed")
    return target


def validate_check_result(check_result: dict[str, Any] | None, result_id: int) -> str | None:
    """Validate check result exists and is fixable.

    Args:
        check_result: Check result from database
        result_id: Result ID for logging

    Returns:
        Error message if validation fails, None if valid
    """
    if not check_result:
        logger.error("check_result_not_found", result_id=result_id)
        return "check_result_not_found"

    check_type = check_result["check_type"]
    if check_type not in SUPPORTED_CHECK_TYPES:
        logger.warning("unsupported_check_type", check_type=check_type)
        return "unsupported_check_type"

    if check_result.get("fixed_at"):
        logger.info("already_fixed", result_id=result_id)
        return "already_fixed"

    return None


def get_project_file_path(
    check_result: dict[str, Any],
    result_id: int,
) -> tuple[Path, Path] | None:
    """Get project and file paths from check result.

    Args:
        check_result: Check result from database
        result_id: Result ID for logging

    Returns:
        Tuple of (project_path, file_path) or None if invalid
    """
    project_id = check_result["project_id"]
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.error("project_not_found", project_id=project_id)
        return None
    project_path = Path(root_path).resolve()

    file_rel_path = check_result.get("file_path")
    if not file_rel_path:
        logger.warning("no_file_path", result_id=result_id)
        return None

    try:
        file_path = resolve_repo_contained_path(project_path, str(file_rel_path))
    except (OSError, ValueError) as exc:
        logger.warning(
            "unsafe_file_path",
            result_id=result_id,
            file_path=str(file_rel_path),
            error=str(exc),
        )
        return None
    return (project_path, file_path)


def filter_lint_type_errors(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter results to only lint/type errors.

    Args:
        results: List of check results

    Returns:
        Filtered list containing only supported check types
    """
    return [r for r in results if r["check_type"] in SUPPORTED_CHECK_TYPES]
