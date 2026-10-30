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
from ...runtime_deployment import (
    DeploymentError,
    ProxmoxDeployment,
    guest_http_status,
    parse_deployment,
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

PROJECT_HEALTH_TIMEOUT_SECONDS = 2.0
GUEST_HEALTH_SSH_ALLOWANCE_SECONDS = 3.0
PROJECT_HEALTH_TIMEOUT = httpx.Timeout(PROJECT_HEALTH_TIMEOUT_SECONDS, connect=0.5)
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


async def probe_guest_health(project_id: str, deployment: ProxmoxDeployment, url: str) -> tuple[str, str]:
    # The SSH hop has its own longer bound; cap it so one hung guest can't stall the project list.
    try:
        status = await asyncio.wait_for(
            asyncio.to_thread(guest_http_status, deployment, url, PROJECT_HEALTH_TIMEOUT_SECONDS),
            PROJECT_HEALTH_TIMEOUT_SECONDS + GUEST_HEALTH_SSH_ALLOWANCE_SECONDS,
        )
    except (DeploymentError, TimeoutError):
        return project_id, "warning"
    return project_id, "healthy" if status == 200 else "warning"


def project_health_target(
    project_id: str, base_url: str, endpoint: str
) -> tuple[str, str, ProxmoxDeployment | None]:
    """Probe the backend the project's identity declares, else its registry URL.

    Registry rows go stale or point at an owner-gated frontend route (403), so a
    healthy service would show as a warning. A Proxmox placement's backend binds
    the guest's loopback, so it is probed from inside that guest.
    """
    try:
        runtime = (get_project_identity(project_id) or {}).get("runtime")
        if not isinstance(runtime, dict):
            return base_url, endpoint, None
        deployment = parse_deployment(runtime.get("deployment"))
    except (OSError, ValueError, DeploymentError):
        return base_url, endpoint, None
    backend = local_url(project_id, "backend_port")
    if not backend:
        return base_url, endpoint, None
    return backend, runtime.get("health_endpoint") or "/health", deployment


def clear_project_health_cache() -> None:
    _health_cache.clear()


async def resolve_project_health_statuses(
    projects: Iterable[tuple[str, str, str]],
) -> dict[str, str]:
    """Fetch live health labels, reusing probes younger than the cache TTL."""
    now = time.monotonic()
    statuses: dict[str, str] = {}
    to_probe: list[tuple[str, str, str, ProxmoxDeployment | None]] = []
    for project_id, registry_url, registry_endpoint in projects:
        base_url, endpoint, deployment = project_health_target(project_id, registry_url, registry_endpoint)
        if not base_url:
            statuses[project_id] = UNCONFIGURED_HEALTH_STATUS
            continue
        cached = _health_cache.get((project_id, base_url, endpoint))
        if cached and now - cached[0] < PROJECT_HEALTH_CACHE_TTL_SECONDS:
            statuses[project_id] = cached[1]
        else:
            to_probe.append((project_id, base_url, endpoint, deployment))
    if not to_probe:
        return statuses
    async with httpx.AsyncClient(timeout=PROJECT_HEALTH_TIMEOUT) as client:
        results = await asyncio.gather(
            *(
                probe_guest_health(project_id, deployment, url + endpoint)
                if deployment
                else probe_project_health(client, project_id, url, endpoint)
                for project_id, url, endpoint, deployment in to_probe
            )
        )
    probed_at = time.monotonic()
    for (project_id, url, endpoint, _), (_, status) in zip(to_probe, results, strict=True):
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

    base_url, endpoint, deployment = project_health_target(project_id, row[0] or "", row[1] or "")
    if not base_url:
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=True,
            checked_at=datetime.now(UTC),
        )

    url = f"{base_url}{endpoint}"
    if deployment:
        start = datetime.now(UTC)
        status_code: int | None = None
        error: str | None = None
        try:
            status_code = await asyncio.to_thread(guest_http_status, deployment, url, HEALTH_CHECK_FULL_TIMEOUT)
        except DeploymentError as exc:
            error = str(exc)
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=status_code == 200,
            endpoint=f"{url} in {deployment.label}",
            status_code=status_code,
            error=error,
            response_time_ms=(datetime.now(UTC) - start).total_seconds() * 1000,
            checked_at=datetime.now(UTC),
        )
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_FULL_TIMEOUT) as client:
            start = datetime.now(UTC)
            response = await client.get(url)
            elapsed = (datetime.now(UTC) - start).total_seconds() * 1000
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=response.status_code == 200,
            endpoint=url,
            status_code=response.status_code,
            response_time_ms=elapsed,
            checked_at=datetime.now(UTC),
        )
    except httpx.RequestError as exc:
        return ProjectHealthResponse(
            project_id=project_id,
            healthy=False,
            endpoint=url,
            error=str(exc),
            checked_at=datetime.now(UTC),
        )


def project_is_active(row: ProjectListRow) -> bool:
    """Routine discovery excludes retired projects and canonical testing fixtures."""
    return row[6] != "testing" and get_project_lifecycle(row[0], row[5]) == "active"
