"""Database helper functions for projects API."""

from datetime import UTC, datetime

from fastapi import HTTPException

from ...storage.connection import get_connection
from .models import ProjectResponse, ProjectStats, ProjectWithStats


def verify_project_exists(project_id: str) -> None:
    """Verify that a project exists, raise HTTPException if not."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


def get_project_from_db(project_id: str) -> ProjectResponse:
    """Fetch a project from the database by ID."""
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


def fetch_project_stats(project_ids: list[str]) -> dict[str, ProjectStats]:
    """Fetch aggregated stats for multiple projects."""
    with get_connection() as conn, conn.cursor() as cur:
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

    # Build stats dict
    stats_dict = {}
    for project_id in project_ids:
        stats_dict[project_id] = ProjectStats(
            tasks=task_counts.get(project_id, 0),
            bugs=bug_counts.get(project_id, 0),
            blocked=blocked_counts.get(project_id, 0),
        )
    return stats_dict


def build_project_with_stats(
    row: tuple[str, str, str, str, str | None, datetime], stats: ProjectStats
) -> ProjectWithStats:
    """Build a ProjectWithStats object from a database row and stats."""
    return ProjectWithStats(
        id=row[0],
        name=row[1],
        base_url=row[2],
        health_endpoint=row[3],
        root_path=row[4],
        logo_url=None,  # Logo support will be added later
        created_at=row[5],
        stats=stats,
    )


def create_project_in_db(
    project_id: str,
    name: str,
    base_url: str,
    health_endpoint: str,
    root_path: str | None,
) -> ProjectResponse:
    """Create a new project in the database."""
    with get_connection() as conn, conn.cursor() as cur:
        # Check if already exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail=f"Project {project_id} already exists")

        # Insert
        now = datetime.now(UTC)
        cur.execute(
            """
                INSERT INTO projects (id, name, base_url, health_endpoint, root_path, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, name, base_url, health_endpoint, root_path, created_at
                """,
            (project_id, name, base_url, health_endpoint, root_path, now),
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
