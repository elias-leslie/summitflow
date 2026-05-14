"""Database helper functions for projects API."""

from datetime import UTC, datetime
from typing import Any, cast

import psycopg
from fastapi import HTTPException
from psycopg import sql

from ...project_identity import canonicalize_project_name
from ...storage.connection import get_connection, get_cursor
from .models import ProjectCategory, ProjectResponse, ProjectStats, ProjectUpdate, ProjectWithStats
from .public_urls import build_project_urls, resolve_project_public_url

PROJECT_COLUMNS = (
    "id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at"
)
ProjectRow = tuple[str, str, str, str | None, str, str | None, ProjectCategory, int | None, datetime]

PROJECT_NOT_FOUND_DETAIL = "Project {project_id} not found"
PROJECT_EXISTS_DETAIL = "Project {project_id} already exists"
PROJECT_CREATE_FAILED_DETAIL = "Failed to create project"
NO_FIELDS_TO_UPDATE_DETAIL = "No fields to update"
BASE_URL_REQUIRED_DETAIL = (
    "Project base URL is required unless SummitFlow-hosted defaults are configured"
)
INACTIVE_TASK_STATUSES = ("completed", "failed", "cancelled", "abandoned")
PROJECT_TASK_TYPE = "project"
BLOCKS_DEPENDENCY_TYPE = "blocks"
PUBLIC_URL_COLUMN = "public_url"
ROOT_PATH_FIELD = "root_path"
BASE_URL_FIELD = "base_url"


def _project_response_from_row(row: ProjectRow) -> ProjectResponse:
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


def _fetch_project_row(cur: psycopg.Cursor[Any], project_id: str) -> ProjectRow | None:
    cur.execute(
        f"""
            SELECT {PROJECT_COLUMNS}
            FROM projects
            WHERE id = %s
            """,
        (project_id,),
    )
    row = cur.fetchone()
    return cast(ProjectRow | None, row)


def _raise_project_not_found(project_id: str) -> None:
    raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND_DETAIL.format(project_id=project_id))


def _require_project_row(row: ProjectRow | None, project_id: str) -> ProjectRow:
    if row is None:
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND_DETAIL.format(project_id=project_id))
    return row


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
        row = _require_project_row(_fetch_project_row(cur, project_id), project_id)

    return _project_response_from_row(row)


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
          AND status NOT IN %s
        GROUP BY project_id
        """,
        (project_ids, task_type, INACTIVE_TASK_STATUSES),
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
          AND t.status NOT IN %s
          AND td.dependency_type = %s
          AND dep.status NOT IN %s
        GROUP BY t.project_id
        """,
        (project_ids, INACTIVE_TASK_STATUSES, BLOCKS_DEPENDENCY_TYPE, INACTIVE_TASK_STATUSES),
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
    row: ProjectRow,
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
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail=PROJECT_EXISTS_DETAIL.format(project_id=project_id))

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
                datetime.now(UTC),
            ),
        )
        row = cur.fetchone()
        sync_project_backup_source(cur, project_id, canonical_name, root_path)
        conn.commit()

    if not row:
        raise HTTPException(status_code=500, detail=PROJECT_CREATE_FAILED_DETAIL)

    return _project_response_from_row(row)


def delete_project_in_db(project_id: str) -> None:
    """Delete a project plus its matching backup source."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def _project_url_update_state(
    project_id: str,
    current: ProjectRow,
    update: ProjectUpdate,
) -> tuple[bool, bool, bool, str | None, str | None]:
    root_path_updated = ROOT_PATH_FIELD in update.model_fields_set
    base_url_updated = BASE_URL_FIELD in update.model_fields_set
    public_url_updated = PUBLIC_URL_COLUMN in update.model_fields_set
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
    return root_path_updated, base_url_updated, public_url_updated, merged_base_url, merged_public_url


def _build_project_field_map(
    project_id: str,
    current: ProjectRow,
    update: ProjectUpdate,
    root_path_updated: bool,
    base_url_updated: bool,
    merged_base_url: str | None,
) -> dict[str, object | None]:
    return {
        "name": (
            canonicalize_project_name(
                project_id,
                update.name,
                update.root_path if root_path_updated else current[5],
            )
            if update.name is not None
            else None
        ),
        BASE_URL_FIELD: merged_base_url if base_url_updated else None,
        "health_endpoint": update.health_endpoint,
        ROOT_PATH_FIELD: update.root_path,
        "category": update.category,
        "sidebar_rank": update.sidebar_rank,
    }


def _build_project_update_parts(
    field_map: dict[str, object | None],
) -> tuple[list[sql.Composable], list[object]]:
    updates: list[sql.Composable] = [
        sql.SQL("{} = {}").format(sql.Identifier(col), sql.Placeholder())
        for col, val in field_map.items()
        if val is not None
    ]
    params = [val for val in field_map.values() if val is not None]
    return updates, params


def update_project_in_db(project_id: str, update: ProjectUpdate) -> ProjectResponse:
    """Apply partial updates to a project and return the updated record."""
    with get_connection() as conn, conn.cursor() as cur:
        current = _require_project_row(_fetch_project_row(cur, project_id), project_id)

        (
            root_path_updated,
            base_url_updated,
            public_url_updated,
            merged_base_url,
            merged_public_url,
        ) = _project_url_update_state(project_id, current, update)
        if base_url_updated and merged_base_url is None:
            raise HTTPException(status_code=400, detail=BASE_URL_REQUIRED_DETAIL)

        field_map = _build_project_field_map(
            project_id,
            current,
            update,
            root_path_updated,
            base_url_updated,
            merged_base_url,
        )
        updates, params = _build_project_update_parts(field_map)
        if public_url_updated or base_url_updated or root_path_updated:
            if merged_public_url is None:
                updates.append(sql.SQL(f"{PUBLIC_URL_COLUMN} = NULL"))
            else:
                updates.append(
                    sql.SQL("{} = {}").format(
                        sql.Identifier(PUBLIC_URL_COLUMN),
                        sql.Placeholder(),
                    )
                )
                params.append(merged_public_url)

        if not updates:
            raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE_DETAIL)

        params.append(project_id)
        query = sql.SQL(
            f"UPDATE projects SET {{updates}} WHERE id = %s RETURNING {PROJECT_COLUMNS}"
        ).format(updates=sql.SQL(", ").join(updates))
        cur.execute(query, params)
        row = cast(ProjectRow | None, cur.fetchone())
        if row:
            sync_project_backup_source(cur, row[0], row[1], row[5])
        conn.commit()

    return _project_response_from_row(_require_project_row(row, project_id))
