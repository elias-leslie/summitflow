"""Projects API - Register and manage target applications."""

import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...services import explorer
from ...storage.project_identity_sync import (
    sync_project_identity as sync_registered_project_identity,
)
from .agent_hub import (
    delete_agent_hub_project_permission,
    reconcile_agent_hub_project_identity,
    sync_agent_hub_project_permission,
)
from .db_helpers import (
    build_project_with_stats,
    create_project_in_db,
    delete_project_in_db,
    fetch_project_stats,
    get_project_from_db,
    update_project_in_db,
)
from .lifecycle import (
    queue_existing_project_onboarding,
    queue_project_create_work,
    resolve_project_create_urls,
    validate_existing_project_onboarding,
)
from .listing import (
    build_project_response,
    check_registered_project_health,
    list_project_rows,
    resolve_project_health_statuses,
)
from .models import (
    ProjectCreate,
    ProjectHealthResponse,
    ProjectOnboardingRequest,
    ProjectOnboardingResponse,
    ProjectResponse,
    ProjectsWithStatsResponse,
    ProjectUpdate,
)
from .onboarding import build_onboarding_response, run_project_onboarding
from .pulse import router as pulse_router

router = APIRouter()
router.include_router(pulse_router, tags=["projects"])


async def _resolve_project_health_statuses(projects):
    return await resolve_project_health_statuses(projects)


@router.post("", response_model=ProjectResponse)
async def create_project(
    project: ProjectCreate, background_tasks: BackgroundTasks
) -> ProjectResponse:
    """Register a new project.

    Triggers an initial Explorer scan for all types in the background.
    """
    effective_base_url, effective_public_url = resolve_project_create_urls(project)
    response = create_project_in_db(
        project.id,
        project.name,
        effective_base_url,
        effective_public_url,
        project.health_endpoint,
        project.root_path,
        project.category,
    )

    if project.agent_hub_permission is not None:
        try:
            await sync_agent_hub_project_permission(
                project.id,
                project.agent_hub_permission,
                project.root_path,
            )
        except Exception:
            delete_project_in_db(project.id)
            raise

    queue_project_create_work(
        project,
        background_tasks,
        onboarding_runner=run_project_onboarding,
        scan_runner=explorer.run_scan_job,
    )
    return response


@router.get("", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    """List all registered projects."""
    rows = list_project_rows()
    health_statuses = await _resolve_project_health_statuses(
        (row[0], row[2], row[4]) for row in rows
    )
    return [build_project_response(row, health_statuses.get(row[0])) for row in rows]


@router.get("/with-stats", response_model=ProjectsWithStatsResponse)
async def list_projects_with_stats() -> ProjectsWithStatsResponse:
    """List all projects with aggregated stats (features, tasks, bugs, blocked)."""
    projects = list_project_rows()

    if not projects:
        return ProjectsWithStatsResponse(projects=[], total=0)

    stats_dict = fetch_project_stats([p[0] for p in projects])
    health_statuses = await _resolve_project_health_statuses(
        (row[0], row[2], row[4]) for row in projects
    )
    result = [build_project_with_stats(row, stats_dict[row[0]]) for row in projects]
    for project in result:
        project.health_status = health_statuses.get(project.id)
    return ProjectsWithStatsResponse(projects=result, total=len(result))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    """Get a specific project."""
    project = get_project_from_db(project_id)
    project.health_status = (
        await _resolve_project_health_statuses(
            [(project.id, project.base_url, project.health_endpoint)]
        )
    ).get(project.id)
    return project


@router.post("/{project_id}/sync-identity", response_model=ProjectResponse)
async def sync_project_identity(project_id: str) -> ProjectResponse:
    """Reconcile a registered project with its repo-local identity manifest."""
    try:
        synced = await asyncio.to_thread(sync_registered_project_identity, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await reconcile_agent_hub_project_identity(
        requested_project_id=project_id,
        canonical_project_id=str(synced["id"]),
        aliases=tuple(str(alias) for alias in synced.get("aliases", ())),
        root_path=synced.get("root_path"),
    )
    return get_project_from_db(str(synced["id"]))


@router.get("/{project_id}/health", response_model=ProjectHealthResponse)
async def check_project_health(project_id: str) -> ProjectHealthResponse:
    """Check health of a registered project."""
    return await check_registered_project_health(project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, update: ProjectUpdate) -> ProjectResponse:
    """Update a project."""
    return update_project_in_db(project_id, update)


@router.post("/{project_id}/onboard", response_model=ProjectOnboardingResponse)
async def onboard_project(
    project_id: str,
    request: ProjectOnboardingRequest,
    background_tasks: BackgroundTasks,
) -> ProjectOnboardingResponse:
    """Queue standard SummitFlow onboarding for an existing project."""
    project = get_project_from_db(project_id)
    validate_existing_project_onboarding(project_id, project.root_path)
    queue_existing_project_onboarding(
        project_id,
        request,
        background_tasks,
        onboarding_runner=run_project_onboarding,
    )
    return build_onboarding_response(project_id, request)


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete a project."""
    project = get_project_from_db(project_id)
    await delete_agent_hub_project_permission(project_id)
    delete_project_in_db(project_id)
    return {"status": "deleted", "project_id": project.id}
