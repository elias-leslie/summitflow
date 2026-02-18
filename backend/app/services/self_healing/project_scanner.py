"""Project scanning for unfixed quality gate errors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from ...storage.projects import list_projects

if TYPE_CHECKING:
    import psycopg

logger = get_logger(__name__)


def get_projects_with_unfixed_errors(
    conn: psycopg.Connection[Any],
) -> dict[str, dict[str, int]]:
    """Get all projects that have unfixed quality gate errors.

    Args:
        conn: Database connection

    Returns:
        Dict mapping project_id → {check_type → count}
    """
    projects_with_errors: dict[str, dict[str, int]] = {}

    # Get all active projects
    projects = list_projects()

    for project in projects:
        project_id = project["id"]
        unfixed_counts: dict[str, int] = {}

        # Check each fixable check type
        for check_type in ["ruff", "types", "biome", "tsc"]:
            count = qcr_store.get_unfixed_count(
                conn,
                project_id,
                check_type=check_type,
            )
            if count > 0:
                unfixed_counts[check_type] = count

        if unfixed_counts:
            projects_with_errors[project_id] = unfixed_counts
            logger.debug(
                "project_has_unfixed",
                project_id=project_id,
                counts=unfixed_counts,
            )

    return projects_with_errors
