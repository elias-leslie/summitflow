"""Projects API - Register and manage target applications."""

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage.connection import get_connection

router = APIRouter()


class ProjectCreate(BaseModel):
    """Request model for creating a project."""

    id: str
    name: str
    base_url: str
    health_endpoint: str = "/health"
    root_path: str | None = None  # Filesystem path for file scanning


class ProjectResponse(BaseModel):
    """Response model for a project."""

    id: str
    name: str
    base_url: str
    health_endpoint: str
    root_path: str | None = None
    created_at: datetime
    health_status: str | None = None


class ProjectHealthResponse(BaseModel):
    """Response model for project health check."""

    project_id: str
    healthy: bool
    status_code: int | None = None
    response_time_ms: float | None = None
    error: str | None = None
    checked_at: datetime


@router.post("", response_model=ProjectResponse)
async def create_project(project: ProjectCreate) -> ProjectResponse:
    """Register a new project."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if already exists
            cur.execute("SELECT id FROM projects WHERE id = %s", (project.id,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail=f"Project {project.id} already exists")

            # Insert
            now = datetime.now(UTC)
            cur.execute(
                """
                INSERT INTO projects (id, name, base_url, health_endpoint, root_path, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, name, base_url, health_endpoint, root_path, created_at
                """,
                (project.id, project.name, project.base_url, project.health_endpoint, project.root_path, now),
            )
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=500, detail="Failed to create project")

    return ProjectResponse(
        id=row[0],
        name=row[1],
        base_url=row[2],
        health_endpoint=row[3],
        root_path=row[4],
        created_at=row[5],
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    """List all registered projects."""
    with get_connection() as conn:
        with conn.cursor() as cur:
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


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    """Get a specific project."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, base_url, health_endpoint, root_path, created_at
                FROM projects
                WHERE id = %s
                """,
                (project_id,),
            )
            row = cur.fetchone()

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


@router.get("/{project_id}/health", response_model=ProjectHealthResponse)
async def check_project_health(project_id: str) -> ProjectHealthResponse:
    """Check health of a registered project."""
    # Get project
    with get_connection() as conn:
        with conn.cursor() as cur:
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


class ProjectUpdate(BaseModel):
    """Request model for updating a project."""

    name: str | None = None
    base_url: str | None = None
    health_endpoint: str | None = None
    root_path: str | None = None


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, update: ProjectUpdate) -> ProjectResponse:
    """Update a project."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if project exists
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

            # Build update query dynamically
            updates = []
            params = []
            if update.name is not None:
                updates.append("name = %s")
                params.append(update.name)
            if update.base_url is not None:
                updates.append("base_url = %s")
                params.append(update.base_url)
            if update.health_endpoint is not None:
                updates.append("health_endpoint = %s")
                params.append(update.health_endpoint)
            if update.root_path is not None:
                updates.append("root_path = %s")
                params.append(update.root_path)

            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")

            params.append(project_id)
            cur.execute(
                f"""
                UPDATE projects SET {', '.join(updates)}
                WHERE id = %s
                RETURNING id, name, base_url, health_endpoint, root_path, created_at
                """,
                params,
            )
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=500, detail="Failed to update project")

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
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s RETURNING id", (project_id,))
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return {"status": "deleted", "id": project_id}
