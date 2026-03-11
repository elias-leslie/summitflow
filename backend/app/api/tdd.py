"""TDD API endpoints - Auto-suggest TDD structure.

Provides endpoints for:
- GET /projects/{project_id}/tdd/suggestions - Get TDD structure suggestions
- GET /projects/{project_id}/tdd/component-suggestions - Get filtered component suggestions
"""

from typing import Any

from fastapi import APIRouter, Query

from ..services.tdd import get_component_suggestions_by_source, get_tdd_suggestions
from .dependencies import validate_project_exists

router = APIRouter()


@router.get("/projects/{project_id}/tdd/suggestions")
async def get_suggestions(project_id: str) -> dict[str, Any]:
    """Get TDD structure suggestions for a project.

    Analyzes explorer data to suggest:
    - Components: Groups of related files/endpoints
    - Existing tests: Test files that match suggested capabilities
    - Coverage summary: How much of the codebase is covered by capabilities

    Returns suggestions to help bootstrap TDD structure.
    """
    validate_project_exists(project_id)

    return get_tdd_suggestions(project_id)


@router.get("/projects/{project_id}/tdd/component-suggestions")
async def get_component_suggestions(
    project_id: str,
    source: str = Query(
        default="manual", description="Source type: pages, endpoints, directories, manual"
    ),
) -> list[dict[str, Any]]:
    """Get component suggestions filtered by source type.

    Used by the Components page to show suggestions based on project settings.
    Returns an empty list when source is 'manual' (no auto-suggestions).
    """
    validate_project_exists(project_id)

    return get_component_suggestions_by_source(project_id, source)
