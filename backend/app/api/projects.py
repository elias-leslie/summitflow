"""Projects API - Register and manage target applications."""

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..constants import VALID_CLAUDE_MODELS, VALID_GEMINI_MODELS
from ..services import explorer
from ..storage import agent_configs
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
    with get_connection() as conn, conn.cursor() as cur:
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

    # Component management
    component_source: str = "manual"

    # Autonomous execution
    autonomous_enabled: bool = False
    autonomous_start_hour: int = 0
    autonomous_end_hour: int = 24
    autonomous_max_concurrent: int = 1

    # Extraction throttle
    extraction_enabled: bool = True
    extraction_rpm_limit: int = 10


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

    # Component management
    component_source: str | None = None

    # Autonomous execution
    autonomous_enabled: bool | None = None

    # Extraction throttle
    extraction_enabled: bool | None = None
    extraction_rpm_limit: int | None = None


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
    from typing import Any

    config_update: dict[str, Any] = {}
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
        if update.claude_model not in VALID_CLAUDE_MODELS:
            raise HTTPException(
                status_code=400, detail=f"claude_model must be one of: {VALID_CLAUDE_MODELS}"
            )
        config_update["claude_model"] = update.claude_model
    if update.gemini_model is not None:
        if update.gemini_model not in VALID_GEMINI_MODELS:
            raise HTTPException(
                status_code=400, detail=f"gemini_model must be one of: {VALID_GEMINI_MODELS}"
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

    # Component management
    if update.component_source is not None:
        valid_sources = ("pages", "endpoints", "directories", "manual")
        if update.component_source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"component_source must be one of: {valid_sources}",
            )
        config_update["component_source"] = update.component_source

    # Autonomous execution
    if update.autonomous_enabled is not None:
        config_update["autonomous_enabled"] = update.autonomous_enabled

    # Extraction throttle
    if update.extraction_enabled is not None:
        config_update["extraction_enabled"] = update.extraction_enabled
    if update.extraction_rpm_limit is not None:
        valid_rpm = (0, 5, 10, 15, 30, 60)
        if update.extraction_rpm_limit not in valid_rpm:
            raise HTTPException(
                status_code=400,
                detail=f"extraction_rpm_limit must be one of: {valid_rpm}",
            )
        config_update["extraction_rpm_limit"] = update.extraction_rpm_limit

    if not config_update:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = agent_configs.update_agent_config(project_id, config_update)  # type: ignore[arg-type]
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update agent config")
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


# ============================================================================
# Automation Settings
# ============================================================================


class AutomationSettings(BaseModel):
    """Automation settings for crowdsourced idea processing."""

    schedule_preset: str = "nightly"  # nightly, weekly, monthly
    cron_expression: str = "0 3 * * *"
    daily_budget_usd: float = 5.0
    primary_agent: str = "gemini"
    secondary_agent: str = "claude"
    enabled: bool = False


DEFAULT_AUTOMATION_SETTINGS = {
    "schedule_preset": "nightly",
    "cron_expression": "0 3 * * *",
    "daily_budget_usd": 5.0,
    "primary_agent": "gemini",
    "secondary_agent": "claude",
    "enabled": False,
}


@router.get("/{project_id}/settings/automation", response_model=AutomationSettings)
async def get_automation_settings(project_id: str) -> AutomationSettings:
    """Get automation settings for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT automation_settings FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    settings = row[0] or DEFAULT_AUTOMATION_SETTINGS
    return AutomationSettings(**settings)


@router.put("/{project_id}/settings/automation", response_model=AutomationSettings)
async def update_automation_settings(
    project_id: str, settings: AutomationSettings
) -> AutomationSettings:
    """Update automation settings for a project."""
    # Validate agents
    if settings.primary_agent not in ("claude", "gemini"):
        raise HTTPException(status_code=400, detail="primary_agent must be 'claude' or 'gemini'")
    if settings.secondary_agent not in ("claude", "gemini"):
        raise HTTPException(status_code=400, detail="secondary_agent must be 'claude' or 'gemini'")

    # Validate budget
    if settings.daily_budget_usd < 0:
        raise HTTPException(status_code=400, detail="daily_budget_usd cannot be negative")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        cur.execute(
            "UPDATE projects SET automation_settings = %s WHERE id = %s",
            (settings.model_dump_json(), project_id),
        )
        conn.commit()

    return settings
