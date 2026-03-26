"""Projects API - Register and manage target applications."""

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from psycopg import sql

from ...services import explorer
from ...storage.connection import get_connection, get_cursor
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
    sync_project_backup_source,
)
from .models import (
    ProjectCreate,
    ProjectHealthResponse,
    ProjectResponse,
    ProjectsWithStatsResponse,
    ProjectUpdate,
)
from .pulse import router as pulse_router

router = APIRouter()

router.include_router(pulse_router, tags=["projects"])


@router.post("", response_model=ProjectResponse)
async def create_project(
    project: ProjectCreate, background_tasks: BackgroundTasks
) -> ProjectResponse:
    """Register a new project.

    Triggers an initial Explorer scan for all types in the background.
    """
    response = create_project_in_db(
        project.id,
        project.name,
        project.base_url,
        project.health_endpoint,
        project.root_path,
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

    # Trigger initial Explorer scan in background (all types)
    background_tasks.add_task(
        explorer.run_scan_job,
        project.id,
        None,
        triggered_by="project_create",
    )

    return response


@router.get("", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    """List all registered projects."""
    with get_cursor() as cur:
        cur.execute(
            """
                SELECT id, name, base_url, health_endpoint, root_path, created_at
                FROM projects
                ORDER BY created_at DESC
                """
        )
        rows = cur.fetchall()

    return [
        ProjectResponse(
            id=row[0],
            name=row[1],
            base_url=row[2],
            health_endpoint=row[3],
            root_path=row[4],
            created_at=row[5],
        )
        for row in rows
    ]


@router.get("/with-stats", response_model=ProjectsWithStatsResponse)
async def list_projects_with_stats() -> ProjectsWithStatsResponse:
    """List all projects with aggregated stats (features, tasks, bugs, blocked)."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, base_url, health_endpoint, root_path, created_at
            FROM projects
            ORDER BY created_at DESC
            """
        )
        projects = cur.fetchall()

    if not projects:
        return ProjectsWithStatsResponse(projects=[], total=0)

    project_ids = [p[0] for p in projects]
    stats_dict = fetch_project_stats(project_ids)

    result = [build_project_with_stats(row, stats_dict[row[0]]) for row in projects]
    return ProjectsWithStatsResponse(projects=result, total=len(result))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    """Get a specific project."""
    return get_project_from_db(project_id)


@router.get("/{project_id}/health", response_model=ProjectHealthResponse)
async def check_project_health(project_id: str) -> ProjectHealthResponse:
    """Check health of a registered project."""
    # Get project
    with get_cursor() as cur:
        cur.execute(
            "SELECT base_url, health_endpoint FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    base_url, health_endpoint = row
    url = f"{base_url}{health_endpoint}"

    # Check health
    try:
        async with httpx.AsyncClient(timeout=10) as client:
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
    with get_connection() as conn, conn.cursor() as cur:
        # Check if project exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        # Build update query dynamically
        updates: list[sql.Composed] = []
        params: list[object] = []
        if update.name is not None:
            updates.append(sql.SQL("name = {}").format(sql.Placeholder()))
            params.append(update.name)
        if update.base_url is not None:
            updates.append(sql.SQL("base_url = {}").format(sql.Placeholder()))
            params.append(update.base_url)
        if update.health_endpoint is not None:
            updates.append(sql.SQL("health_endpoint = {}").format(sql.Placeholder()))
            params.append(update.health_endpoint)
        if update.root_path is not None:
            updates.append(sql.SQL("root_path = {}").format(sql.Placeholder()))
            params.append(update.root_path)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(project_id)
        query = sql.SQL(
            """
                UPDATE projects SET {updates}
                WHERE id = %s
                RETURNING id, name, base_url, health_endpoint, root_path, created_at
                """
        ).format(updates=sql.SQL(", ").join(updates))
        cur.execute(query, params)
        row = cur.fetchone()
        if row:
            sync_project_backup_source(cur, row[0], row[1], row[4])
        conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return ProjectResponse(
        id=row[0],
        name=row[1],
        base_url=row[2],
        health_endpoint=row[3],
        root_path=row[4],
        created_at=row[5],
    )


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete a project."""
    project = get_project_from_db(project_id)
    await delete_agent_hub_project_permission(project_id)
    delete_project_in_db(project_id)

    return {"status": "deleted", "project_id": project.id}
    return {"status": "deleted", "id": project_id}
