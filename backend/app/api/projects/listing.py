"""Project listing and health helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast

import httpx

from ...project_identity import canonicalize_project_name
from ...storage.connection import get_cursor
from .models import ProjectCategory, ProjectHealthResponse, ProjectResponse
from .public_urls import resolve_project_public_url

ProjectListRow = tuple[
    str,
    str,
    str,
    str | None,
    str,
    str | None,
    ProjectCategory,
    int | None,
    datetime,
]

PROJECT_HEALTH_TIMEOUT = httpx.Timeout(2.0, connect=0.5)
HEALTH_CHECK_FULL_TIMEOUT = 10

SQL_LIST_PROJECTS = """
    SELECT id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at
    FROM projects
"""


async def probe_project_health(
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


async def resolve_project_health_statuses(
    projects: Iterable[tuple[str, str, str]],
) -> dict[str, str]:
    """Fetch live health labels for project list/detail responses."""
    targets = list(projects)
    if not targets:
        return {}
    async with httpx.AsyncClient(timeout=PROJECT_HEALTH_TIMEOUT) as client:
        results = await asyncio.gather(
            *(
                probe_project_health(client, project_id, url, endpoint)
                for project_id, url, endpoint in targets
            )
        )
    return dict(results)


def list_project_rows() -> list[ProjectListRow]:
    """Fetch and sort all project rows for list-style responses."""
    with get_cursor() as cur:
        cur.execute(SQL_LIST_PROJECTS)
        return cast(list[ProjectListRow], sorted(cur.fetchall(), key=project_sort_key))


def build_project_response(
    row: ProjectListRow,
    health_status: str | None = None,
) -> ProjectResponse:
    """Build API response model for one raw project row."""
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
        health_status=health_status,
    )


def project_sort_key(row: ProjectListRow) -> tuple[int, int, int, str, float]:
    category_rank = {
        "production": 0,
        "testing": 1,
    }.get(row[6], 2)
    sidebar_rank = row[7] if row[7] is not None else 10_000
    canonical_name = canonicalize_project_name(row[0], row[1], row[5]) or row[1]
    created_sort = -row[8].timestamp()
    return (
        category_rank,
        1 if row[7] is None else 0,
        sidebar_rank,
        canonical_name.lower(),
        created_sort,
    )


async def check_registered_project_health(project_id: str) -> ProjectHealthResponse:
    with get_cursor() as cur:
        cur.execute(
            "SELECT base_url, health_endpoint FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    url = f"{row[0]}{row[1]}"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_FULL_TIMEOUT) as client:
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
    except httpx.RequestError as exc:
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=False,
            error=str(exc),
            checked_at=datetime.now(UTC),
        )
