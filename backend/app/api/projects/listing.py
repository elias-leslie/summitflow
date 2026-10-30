"""Project listing and health helpers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast

import httpx

from ...local_endpoints import local_url
from ...project_identity import (
    ProjectLifecycle,
    canonicalize_project_name,
    get_project_identity,
    get_project_lifecycle,
    get_project_lifecycles,
)
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


PROJECT_HEALTH_CACHE_TTL_SECONDS = 60.0
UNCONFIGURED_HEALTH_STATUS = "unconfigured"
_health_cache: dict[tuple[str, str, str], tuple[float, str]] = {}


async def probe_project_health(
    client: httpx.AsyncClient,
    project_id: str,
    base_url: str,
    health_endpoint: str,
) -> tuple[str, str]:
    """Return a lightweight health label for project listings."""
    if not base_url:
        return project_id, UNCONFIGURED_HEALTH_STATUS
    try:
        response = await client.get(f"{base_url}{health_endpoint}")
    except httpx.HTTPError:
        return project_id, "warning"
    return project_id, "healthy" if response.status_code == 200 else "warning"


def project_health_target(project_id: str, base_url: str, endpoint: str) -> tuple[str, str]:
    """Probe the local backend the project's identity declares, else its registry URL.

    Registry rows go stale or point at an owner-gated frontend route (403), so a
    healthy local service would show as a warning. Remote placements keep the
    registry URL: their declared port is not on this host.
    """
    try:
        runtime = (get_project_identity(project_id) or {}).get("runtime")
    except (OSError, ValueError):
        return base_url, endpoint
    if not isinstance(runtime, dict) or runtime.get("deployment") is not None:
        return base_url, endpoint
    backend = local_url(project_id, "backend_port")
    return (backend, runtime.get("health_endpoint") or "/health") if backend else (base_url, endpoint)


def clear_project_health_cache() -> None:
    _health_cache.clear()


async def resolve_project_health_statuses(
    projects: Iterable[tuple[str, str, str]],
) -> dict[str, str]:
    """Fetch live health labels, reusing probes younger than the cache TTL."""
    now = time.monotonic()
    statuses: dict[str, str] = {}
    to_probe: list[tuple[str, str, str]] = []
    for project_id, registry_url, registry_endpoint in projects:
        base_url, endpoint = project_health_target(project_id, registry_url, registry_endpoint)
        if not base_url:
            statuses[project_id] = UNCONFIGURED_HEALTH_STATUS
            continue
        cached = _health_cache.get((project_id, base_url, endpoint))
        if cached and now - cached[0] < PROJECT_HEALTH_CACHE_TTL_SECONDS:
            statuses[project_id] = cached[1]
        else:
            to_probe.append((project_id, base_url, endpoint))
    if not to_probe:
        return statuses
    async with httpx.AsyncClient(timeout=PROJECT_HEALTH_TIMEOUT) as client:
        results = await asyncio.gather(
            *(
                probe_project_health(client, project_id, url, endpoint)
                for project_id, url, endpoint in to_probe
            )
        )
    probed_at = time.monotonic()
    for (project_id, url, endpoint), (_, status) in zip(to_probe, results, strict=True):
        _health_cache[(project_id, url, endpoint)] = (probed_at, status)
        statuses[project_id] = status
    return statuses


def list_project_rows(*, include_inactive: bool = False) -> list[ProjectListRow]:
    """Fetch and sort discoverable rows, preserving an explicit full inventory."""
    with get_cursor() as cur:
        cur.execute(SQL_LIST_PROJECTS)
        rows = cast(list[ProjectListRow], sorted(cur.fetchall(), key=project_sort_key))
    if include_inactive:
        return rows
    lifecycles = get_project_lifecycles([row[0] for row in rows])
    return [row for row in rows if row[6] != "testing" and lifecycles[row[0]] == "active"]


def build_project_response(
    row: ProjectListRow,
    health_status: str | None = None,
    lifecycle: ProjectLifecycle | None = None,
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
        lifecycle=lifecycle or get_project_lifecycle(row[0], row[5]),
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

    if not row[0]:
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=True,
            checked_at=datetime.now(UTC),
        )

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


def project_is_active(row: ProjectListRow) -> bool:
    """Routine discovery excludes retired projects and canonical testing fixtures."""
    return row[6] != "testing" and get_project_lifecycle(row[0], row[5]) == "active"
