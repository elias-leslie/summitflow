"""Validation utilities for fix agent.

Handles precondition checks before attempting fixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path

logger = get_logger(__name__)

# Supported check types for automatic fixing
SUPPORTED_CHECK_TYPES = ("ruff", "types", "biome", "tsc")


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
    project_path = Path(root_path)

    file_rel_path = check_result.get("file_path")
    if not file_rel_path:
        logger.warning("no_file_path", result_id=result_id)
        return None

    file_path = project_path / file_rel_path
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
