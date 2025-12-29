"""Memory Observations API - Observation listing and bulk operations.

Endpoints:
- GET /observations - List observations globally
- GET /diary - List diary entries globally
- POST /memory/observations/bulk - Bulk create observations
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..storage import memory as memory_storage
from .memory_models import (
    BulkObservationRequest,
    BulkObservationResponse,
    PaginatedResponse,
)

router = APIRouter()


@router.get("/observations", response_model=PaginatedResponse)
async def list_observations_global(
    project_id: str | None = Query(None, description="Filter by project"),
    agent_type: str | None = Query(None, description="Filter by agent type"),
    observation_type: str | None = Query(None, description="Filter by observation type"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse:
    """List observations across all projects.

    Use project_id query param to filter to a specific project.
    Returns observations sorted by created_at descending (newest first).
    """
    items = memory_storage.list_observations(
        project_id=project_id,
        agent_type=agent_type,
        observation_type=observation_type,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    total = memory_storage.count_observations(
        project_id=project_id,
        agent_type=agent_type,
        observation_type=observation_type,
        session_id=session_id,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/diary", response_model=PaginatedResponse)
async def list_diary_global(
    project_id: str | None = Query(None, description="Filter by project"),
    outcome: str | None = Query(None, description="Filter by outcome"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse:
    """List diary entries across all projects.

    Use project_id query param to filter to a specific project.
    Returns diary entries sorted by created_at descending (newest first).
    """
    items = memory_storage.list_diary_entries(
        project_id=project_id,
        outcome=outcome,
        limit=limit,
        offset=offset,
    )
    total = memory_storage.count_diary_entries(
        project_id=project_id,
        outcome=outcome,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/memory/observations/bulk", response_model=BulkObservationResponse)
async def create_observations_bulk(
    request: BulkObservationRequest,
) -> BulkObservationResponse:
    """Bulk create observations from refactoring or other analysis findings.

    This endpoint accepts an array of observations and creates them in batch,
    reusing the existing create_observation logic for each.

    Useful for:
    - /refactor_it analysis findings capture
    - Bulk migration of external data
    - Importing observations from other tools

    Returns created count, skipped count (duplicates), and any errors.
    """
    created_count = 0
    skipped_count = 0
    errors: list[str] = []

    for idx, obs in enumerate(request.observations):
        try:
            result = memory_storage.create_observation(
                project_id=request.project_id,
                session_id=request.session_id,
                agent_type=request.agent_type,
                observation_type=obs.observation_type,
                title=obs.title,
                narrative=obs.narrative,
                confidence=obs.confidence,
                files_modified=obs.files_modified,
                concepts=obs.concepts,
                facts=obs.facts,
                skip_memory_check=True,  # Bulk ops bypass memory check
            )
            if result:
                created_count += 1
            else:
                skipped_count += 1  # Duplicate or filtered
        except Exception as e:
            errors.append(f"Observation {idx} ({obs.title[:30]}...): {e!s}")

    return BulkObservationResponse(
        created_count=created_count,
        skipped_count=skipped_count,
        errors=errors[:20],  # Limit errors returned
    )
