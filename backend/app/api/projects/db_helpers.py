"""Database helper functions for projects API."""

from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import HTTPException
from psycopg import sql

from ...project_identity import canonicalize_project_name
from ...storage.connection import get_connection, get_cursor
from .models import ProjectCategory, ProjectResponse, ProjectStats, ProjectUpdate, ProjectWithStats
from .public_urls import build_project_urls, resolve_project_public_url


def sync_project_backup_source(
    cur: psycopg.Cursor[Any],
    project_id: str,
    name: str,
    root_path: str | None,
) -> None:
    """Ensure a project-scoped backup source exists and reflects the project root."""
    if not root_path:
        return
    backup_name = canonicalize_project_name(project_id, name, root_path)

    cur.execute(
        """
        INSERT INTO backup_sources (id, name, path, source_type, project_id)
        VALUES (%s, %s, %s, 'project', %s)
        ON CONFLICT (id) DO UPDATE
        SET name = EXCLUDED.name,
            path = EXCLUDED.path,
            project_id = EXCLUDED.project_id,
            updated_at = NOW()
        """,
        (project_id, backup_name, root_path, project_id),
    )


def get_project_from_db(project_id: str) -> ProjectResponse:
    """Fetch a project from the database by ID."""
    with get_cursor() as cur:
        cur.execute(
            """
                SELECT id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at
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
        name=canonicalize_project_name(row[0], row[1], row[5]),
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
    )


def _fetch_active_type_counts(
    cur: psycopg.Cursor[Any],
    project_ids: list[str],
    task_type: str,
) -> dict[str, int]:
    """Fetch active task counts for a specific task type per project."""
    cur.execute(
        """
        SELECT project_id, COUNT(*) as count
        FROM tasks
        WHERE project_id = ANY(%s)
          AND task_type = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'abandoned')
        GROUP BY project_id
        """,
        (project_ids, task_type),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _fetch_feature_counts(cur: psycopg.Cursor[Any], project_ids: list[str]) -> dict[str, int]:
    """Fetch active feature counts per project."""
    return _fetch_active_type_counts(cur, project_ids, "feature")


def _fetch_task_counts(cur: psycopg.Cursor[Any], project_ids: list[str]) -> dict[str, int]:
    """Fetch active regular task counts per project."""
    return _fetch_active_type_counts(cur, project_ids, "task")


def _fetch_bug_counts(cur: psycopg.Cursor[Any], project_ids: list[str]) -> dict[str, int]:
    """Fetch active bug counts per project."""
    return _fetch_active_type_counts(cur, project_ids, "bug")


def _fetch_blocked_counts(cur: psycopg.Cursor[Any], project_ids: list[str]) -> dict[str, int]:
    """Fetch blocked task counts per project."""
    cur.execute(
        """
        SELECT t.project_id, COUNT(DISTINCT t.id) as count
        FROM tasks t
        INNER JOIN task_dependencies td ON t.id = td.task_id
        INNER JOIN tasks dep ON td.depends_on_task_id = dep.id
        WHERE t.project_id = ANY(%s)
          AND t.status NOT IN ('completed', 'failed', 'cancelled', 'abandoned')
          AND td.dependency_type = 'blocks'
          AND dep.status NOT IN ('completed', 'failed', 'cancelled', 'abandoned')
        GROUP BY t.project_id
        """,
        (project_ids,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def fetch_project_stats(project_ids: list[str]) -> dict[str, ProjectStats]:
    """Fetch aggregated stats for multiple projects."""
    with get_cursor() as cur:
        feature_counts = _fetch_feature_counts(cur, project_ids)
        task_counts = _fetch_task_counts(cur, project_ids)
        bug_counts = _fetch_bug_counts(cur, project_ids)
        blocked_counts = _fetch_blocked_counts(cur, project_ids)

    return {
        project_id: ProjectStats(
            features=feature_counts.get(project_id, 0),
            tasks=task_counts.get(project_id, 0),
            bugs=bug_counts.get(project_id, 0),
            blocked=blocked_counts.get(project_id, 0),
        )
        for project_id in project_ids
    }


def build_project_with_stats(
    row: tuple[str, str, str, str | None, str, str | None, ProjectCategory, int | None, datetime],
    stats: ProjectStats,
) -> ProjectWithStats:
    """Build a ProjectWithStats object from a database row and stats."""
    return ProjectWithStats(
        id=row[0],
        name=canonicalize_project_name(row[0], row[1], row[5]),
        base_url=row[2],
        public_url=resolve_project_public_url(
            row[0],
            base_url=row[2],
            public_url=row[3],
            root_path=row[5],
        ),
        health_endpoint=row[4],
        root_path=row[5],
        logo_url=None,  # Logo support will be added later
        category=row[6],
        sidebar_rank=row[7],
        created_at=row[8],
        stats=stats,
    )


def create_project_in_db(
    project_id: str,
    name: str,
    base_url: str,
    public_url: str | None,
    health_endpoint: str,
    root_path: str | None,
    category: str,
) -> ProjectResponse:
    """Create a new project in the database."""
    canonical_name = canonicalize_project_name(project_id, name, root_path)
    with get_connection() as conn, conn.cursor() as cur:
        # Check if already exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail=f"Project {project_id} already exists")

        # Insert
        now = datetime.now(UTC)
        cur.execute(
            """
                INSERT INTO projects (id, name, base_url, public_url, health_endpoint, root_path, category, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at
                """,
            (
                project_id,
                canonical_name,
                base_url,
                public_url,
                health_endpoint,
                root_path,
                category,
                now,
            ),
        )
        row = cur.fetchone()
        sync_project_backup_source(cur, project_id, canonical_name, root_path)
        conn.commit()

    if not row:
        raise HTTPException(status_code=500, detail="Failed to create project")

    return ProjectResponse(
        id=row[0],
        name=canonicalize_project_name(row[0], row[1], row[5]),
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
    )


def delete_project_in_db(project_id: str) -> None:
    """Delete a project plus its matching backup source."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def update_project_in_db(project_id: str, update: ProjectUpdate) -> ProjectResponse:
    """Apply partial updates to a project and return the updated record."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at
            FROM projects
            WHERE id = %s
            """,
            (project_id,),
        )
        current = cur.fetchone()
        if not current:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        root_path_updated = "root_path" in update.model_fields_set
        base_url_updated = "base_url" in update.model_fields_set
        public_url_updated = "public_url" in update.model_fields_set

        merged_base_url, merged_public_url = build_project_urls(
            project_id,
            base_url=update.base_url if base_url_updated else current[2],
            public_url=(
                update.public_url
                if public_url_updated
                else (None if base_url_updated or root_path_updated else current[3])
            ),
            root_path=update.root_path if root_path_updated else current[5],
        )
        if base_url_updated and merged_base_url is None:
            raise HTTPException(
                status_code=400,
                detail="Project base URL is required unless SummitFlow-hosted defaults are configured",
            )

        field_map = {
            "name": (
                canonicalize_project_name(
                    project_id,
                    update.name,
                    update.root_path if root_path_updated else current[5],
                )
                if update.name is not None
                else None
            ),
            "base_url": merged_base_url if base_url_updated else None,
            "health_endpoint": update.health_endpoint,
            "root_path": update.root_path,
            "category": update.category,
            "sidebar_rank": update.sidebar_rank,
        }
        updates: list[sql.Composable] = [
            sql.SQL("{} = {}").format(sql.Identifier(col), sql.Placeholder())
            for col, val in field_map.items()
            if val is not None
        ]
        params: list[object] = [val for val in field_map.values() if val is not None]
        if public_url_updated or base_url_updated or root_path_updated:
            if merged_public_url is None:
                updates.append(sql.SQL("public_url = NULL"))
            else:
                updates.append(
                    sql.SQL("{} = {}").format(
                        sql.Identifier("public_url"),
                        sql.Placeholder(),
                    )
                )
                params.append(merged_public_url)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(project_id)
        query = sql.SQL(
            "UPDATE projects SET {updates} WHERE id = %s"
            " RETURNING id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at"
        ).format(updates=sql.SQL(", ").join(updates))
        cur.execute(query, params)
        row = cur.fetchone()
        if row:
            sync_project_backup_source(cur, row[0], row[1], row[5])
        conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    return ProjectResponse(
        id=row[0],
        name=canonicalize_project_name(row[0], row[1], row[5]),
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
    )
