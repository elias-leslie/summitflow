"""Projects API - Register and manage target applications."""

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...services import explorer
from ...storage import backups as backup_store
from ...storage.connection import get_cursor
from .agent_hub import (
    delete_agent_hub_project_permission,
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
from .public_urls import build_project_urls, resolve_project_public_url
from .pulse import router as pulse_router

router = APIRouter()
router.include_router(pulse_router, tags=["projects"])

# Timeouts
_PROJECT_HEALTH_TIMEOUT = httpx.Timeout(2.0, connect=0.5)
_HEALTH_CHECK_FULL_TIMEOUT = 10

# Triggered-by labels
_TRIGGER_PROJECT_CREATE = "project_create"
_TRIGGER_PROJECT_ONBOARD = "project_onboard"

# Shared SQL
_SQL_LIST_PROJECTS = """
    SELECT id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at
    FROM projects
    ORDER BY
        CASE category
            WHEN 'production' THEN 0
            WHEN 'testing' THEN 1
            ELSE 2
        END,
        CASE WHEN sidebar_rank IS NULL THEN 1 ELSE 0 END,
        sidebar_rank ASC,
        LOWER(name) ASC,
        created_at DESC
"""

# Error messages
_ERR_ONBOARDING_REQUIRES_ROOT = "Project onboarding requires root_path"
_ERR_ONBOARDING_REQUIRES_BACKUP = "Project onboarding requires a backup source"
_ERR_BASE_URL_REQUIRED = (
    "Project base URL is required unless SummitFlow-hosted defaults are configured"
)


async def _probe_project_health(
    client: httpx.AsyncClient,
    project_id: str,
    base_url: str,
    health_endpoint: str,
) -> tuple[str, str]:
    """Return a lightweight health label for project listings."""
    try:
        response = await client.get(f"{base_url}{health_endpoint}")
    except httpx.HTTPError:
        return project_id, "warning"
    return project_id, "healthy" if response.status_code == 200 else "warning"


async def _resolve_project_health_statuses(
    projects: Iterable[tuple[str, str, str]],
) -> dict[str, str]:
    """Fetch live health labels for project list/detail responses."""
    targets = list(projects)
    if not targets:
        return {}
    async with httpx.AsyncClient(timeout=_PROJECT_HEALTH_TIMEOUT) as client:
        results = await asyncio.gather(
            *(
                _probe_project_health(client, pid, url, ep)
                for pid, url, ep in targets
            )
        )
    return dict(results)


@router.post("", response_model=ProjectResponse)
async def create_project(
    project: ProjectCreate, background_tasks: BackgroundTasks
) -> ProjectResponse:
    """Register a new project.

    Triggers an initial Explorer scan for all types in the background.
    """
    if project.onboarding is not None and not project.root_path:
        raise HTTPException(status_code=400, detail=_ERR_ONBOARDING_REQUIRES_ROOT)

    effective_base_url, effective_public_url = build_project_urls(
        project.id,
        base_url=project.base_url,
        public_url=project.public_url,
        root_path=project.root_path,
        summitflow_hosted=project.summitflow_hosted,
    )
    if not effective_base_url:
        raise HTTPException(status_code=400, detail=_ERR_BASE_URL_REQUIRED)

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

    if project.onboarding is not None:
        background_tasks.add_task(
            run_project_onboarding,
            project.id,
            project.onboarding,
            triggered_by=_TRIGGER_PROJECT_CREATE,
        )
    else:
        background_tasks.add_task(
            explorer.run_scan_job,
            project.id,
            None,
            triggered_by=_TRIGGER_PROJECT_CREATE,
        )

    return response


@router.get("", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    """List all registered projects."""
    with get_cursor() as cur:
        cur.execute(_SQL_LIST_PROJECTS)
        rows = cur.fetchall()

    health_statuses = await _resolve_project_health_statuses(
        (row[0], row[2], row[4]) for row in rows
    )
    return [
        ProjectResponse(
            id=row[0],
            name=row[1],
            base_url=row[2],
            public_url=resolve_project_public_url(
                row[0],
                base_url=row[2],
                public_url=row[3],
                root_path=row[5],
            ),
            health_endpoint=row[4],
            root_path=row[5],
            category=row[6],
            sidebar_rank=row[7],
            created_at=row[8],
            health_status=health_statuses.get(row[0]),
        )
        for row in rows
    ]


@router.get("/with-stats", response_model=ProjectsWithStatsResponse)
async def list_projects_with_stats() -> ProjectsWithStatsResponse:
    """List all projects with aggregated stats (features, tasks, bugs, blocked)."""
    with get_cursor() as cur:
        cur.execute(_SQL_LIST_PROJECTS)
        projects = cur.fetchall()

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


@router.get("/{project_id}/health", response_model=ProjectHealthResponse)
async def check_project_health(project_id: str) -> ProjectHealthResponse:
    """Check health of a registered project."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT base_url, health_endpoint FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    url = f"{row[0]}{row[1]}"
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_CHECK_FULL_TIMEOUT) as client:
            start = datetime.now(UTC)
            response = await client.get(url)
            elapsed = (datetime.now(UTC) - start).total_seconds() * 1000
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=response.status_code == 200,
            status_code=response.status_code,
            response_time_ms=elapsed,
            checked_at=datetime.now(UTC),
        )
    except httpx.RequestError as e:
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=False,
            error=str(e),
            checked_at=datetime.now(UTC),
        )


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
    if not project.root_path:
        raise HTTPException(status_code=400, detail=_ERR_ONBOARDING_REQUIRES_ROOT)
    if not backup_store.get_source(project_id):
        raise HTTPException(status_code=400, detail=_ERR_ONBOARDING_REQUIRES_BACKUP)

    background_tasks.add_task(
        run_project_onboarding,
        project_id,
        request,
        triggered_by=_TRIGGER_PROJECT_ONBOARD,
    )
    return build_onboarding_response(project_id, request)


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete a project."""
    project = get_project_from_db(project_id)
    await delete_agent_hub_project_permission(project_id)
    delete_project_in_db(project_id)
    return {"status": "deleted", "project_id": project.id}
