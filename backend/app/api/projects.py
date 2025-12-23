"""Projects API - Register and manage target applications."""

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..services import explorer
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
async def create_project(
    project: ProjectCreate, background_tasks: BackgroundTasks
) -> ProjectResponse:
    """Register a new project.

    Triggers an initial Explorer scan for all types in the background.
    """
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
                (
                    project.id,
                    project.name,
                    project.base_url,
                    project.health_endpoint,
                    project.root_path,
                    now,
                ),
            )
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=500, detail="Failed to create project")

    # Trigger initial Explorer scan in background (all types)
    explorer.start_scan(project.id, None)
    background_tasks.add_task(explorer.run_scan_with_tracking, project.id, None)

    return ProjectResponse(
        id=row[0],
        name=row[1],
        base_url=row[2],
        health_endpoint=row[3],
        root_path=row[4],
        created_at=row[5],
    )


class ProjectStats(BaseModel):
    """Stats for a single project."""

    features: int = 0
    tasks: int = 0
    bugs: int = 0
    blocked: int = 0


class ProjectWithStats(BaseModel):
    """Project with aggregated stats."""

    id: str
    name: str
    base_url: str
    health_endpoint: str
    root_path: str | None = None
    logo_url: str | None = None
    created_at: datetime
    health_status: str | None = None
    stats: ProjectStats


class ProjectsWithStatsResponse(BaseModel):
    """Response for projects list with stats."""

    projects: list[ProjectWithStats]
    total: int


@router.get("", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    """List all registered projects."""
    with get_connection() as conn, conn.cursor() as cur:
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
    with get_connection() as conn, conn.cursor() as cur:
        # Get all projects
        # Note: logo_url column may not exist yet, so we don't select it
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

        # Get capability counts per project (new TDD schema uses capabilities table)
        cur.execute(
            """
            SELECT project_id, COUNT(*) as count
            FROM capabilities
            WHERE project_id = ANY(%s)
            GROUP BY project_id
            """,
            (project_ids,),
        )
        feature_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Get task counts per project (non-bug, active tasks only)
        cur.execute(
            """
            SELECT project_id, COUNT(*) as count
            FROM tasks
            WHERE project_id = ANY(%s)
              AND task_type != 'bug'
              AND status NOT IN ('completed', 'failed')
            GROUP BY project_id
            """,
            (project_ids,),
        )
        task_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Get bug counts per project (active bugs only)
        cur.execute(
            """
            SELECT project_id, COUNT(*) as count
            FROM tasks
            WHERE project_id = ANY(%s)
              AND task_type = 'bug'
              AND status NOT IN ('completed', 'failed')
            GROUP BY project_id
            """,
            (project_ids,),
        )
        bug_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Get blocked task counts per project
        # A task is blocked if it has incomplete dependencies
        cur.execute(
            """
            SELECT t.project_id, COUNT(DISTINCT t.id) as count
            FROM tasks t
            INNER JOIN task_dependencies td ON t.id = td.task_id
            INNER JOIN tasks dep ON td.depends_on_task_id = dep.id
            WHERE t.project_id = ANY(%s)
              AND t.status NOT IN ('completed', 'failed')
              AND td.dependency_type = 'blocks'
              AND dep.status NOT IN ('completed', 'failed')
            GROUP BY t.project_id
            """,
            (project_ids,),
        )
        blocked_counts = {row[0]: row[1] for row in cur.fetchall()}

    result = []
    for row in projects:
        project_id = row[0]
        result.append(
            ProjectWithStats(
                id=project_id,
                name=row[1],
                base_url=row[2],
                health_endpoint=row[3],
                root_path=row[4],
                logo_url=None,  # Logo support will be added later
                created_at=row[5],
                stats=ProjectStats(
                    features=feature_counts.get(project_id, 0),
                    tasks=task_counts.get(project_id, 0),
                    bugs=bug_counts.get(project_id, 0),
                    blocked=blocked_counts.get(project_id, 0),
                ),
            )
        )

    return ProjectsWithStatsResponse(projects=result, total=len(result))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    """Get a specific project."""
    with get_connection() as conn, conn.cursor() as cur:
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
    with get_connection() as conn, conn.cursor() as cur:
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
    with get_connection() as conn, conn.cursor() as cur:
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
                UPDATE projects SET {", ".join(updates)}
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
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s RETURNING id", (project_id,))
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return {"status": "deleted", "id": project_id}


# --- Agent Configuration Endpoints ---

from ..storage import agent_configs


class AgentConfigResponse(BaseModel):
    """Response model for agent configuration."""

    claude_enabled: bool
    gemini_enabled: bool
    default_agent: str
    claude_model: str
    gemini_model: str

    # Memory system controls
    memory_enabled: bool = True
    observations_enabled: bool = True
    diary_enabled: bool = True
    patterns_enabled: bool = True
    checkpoints_enabled: bool = True
    context_injection_enabled: bool = True


class AgentConfigUpdate(BaseModel):
    """Request model for updating agent configuration."""

    claude_enabled: bool | None = None
    gemini_enabled: bool | None = None
    default_agent: str | None = None
    claude_model: str | None = None
    gemini_model: str | None = None

    # Memory system controls
    memory_enabled: bool | None = None
    observations_enabled: bool | None = None
    diary_enabled: bool | None = None
    patterns_enabled: bool | None = None
    checkpoints_enabled: bool | None = None
    context_injection_enabled: bool | None = None


@router.get("/{project_id}/agents", response_model=AgentConfigResponse)
async def get_agent_config(project_id: str) -> AgentConfigResponse:
    """Get agent configuration for a project."""
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    config = agent_configs.get_agent_config(project_id)
    return AgentConfigResponse(**config)


@router.patch("/{project_id}/agents", response_model=AgentConfigResponse)
async def update_agent_config(project_id: str, update: AgentConfigUpdate) -> AgentConfigResponse:
    """Update agent configuration for a project."""
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # Build config update dict from non-None values
    config_update = {}
    if update.claude_enabled is not None:
        config_update["claude_enabled"] = update.claude_enabled
    if update.gemini_enabled is not None:
        config_update["gemini_enabled"] = update.gemini_enabled
    if update.default_agent is not None:
        if update.default_agent not in ("claude", "gemini"):
            raise HTTPException(
                status_code=400, detail="default_agent must be 'claude' or 'gemini'"
            )
        config_update["default_agent"] = update.default_agent
    if update.claude_model is not None:
        valid_claude_models = (
            "claude-sonnet-4-5",
            "claude-opus-4-5",
            "claude-haiku-4-5",
            "sonnet",
            "opus",
            "haiku",
        )
        if update.claude_model not in valid_claude_models:
            raise HTTPException(
                status_code=400, detail=f"claude_model must be one of: {valid_claude_models}"
            )
        config_update["claude_model"] = update.claude_model
    if update.gemini_model is not None:
        valid_models = (
            "gemini-3-flash-preview",
            "gemini-3-pro-preview",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        )
        if update.gemini_model not in valid_models:
            raise HTTPException(
                status_code=400, detail=f"gemini_model must be one of: {valid_models}"
            )
        config_update["gemini_model"] = update.gemini_model

    # Memory system controls - all are simple boolean flags
    if update.memory_enabled is not None:
        config_update["memory_enabled"] = update.memory_enabled
    if update.observations_enabled is not None:
        config_update["observations_enabled"] = update.observations_enabled
    if update.diary_enabled is not None:
        config_update["diary_enabled"] = update.diary_enabled
    if update.patterns_enabled is not None:
        config_update["patterns_enabled"] = update.patterns_enabled
    if update.checkpoints_enabled is not None:
        config_update["checkpoints_enabled"] = update.checkpoints_enabled
    if update.context_injection_enabled is not None:
        config_update["context_injection_enabled"] = update.context_injection_enabled

    if not config_update:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = agent_configs.update_agent_config(project_id, config_update)
    return AgentConfigResponse(**updated)


@router.get("/{project_id}/agents/enabled", response_model=list[str])
async def get_enabled_agents(project_id: str) -> list[str]:
    """Get list of enabled agents for a project."""
    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return agent_configs.get_enabled_agents(project_id)
