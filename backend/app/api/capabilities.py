"""Capabilities scanner API endpoints.

Provides REST API for database/API/Celery capability scanning:
- GET /api/projects/{id}/capabilities/database - list DB capabilities
- POST /api/projects/{id}/capabilities/database/scan - trigger scan
- GET /api/projects/{id}/capabilities/api - list API capabilities
- POST /api/projects/{id}/capabilities/api/scan - trigger API scan
- GET /api/projects/{id}/capabilities/celery - list Celery capabilities
- POST /api/projects/{id}/capabilities/celery/scan - trigger Celery scan
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.api_scanner import APIScanner, get_project_paths
from app.services.celery_scanner import CeleryScanner, get_project_celery_config
from app.services.db_scanner import DatabaseScanner, get_project_db_url
from app.storage.connection import get_connection

router = APIRouter(tags=["capabilities"])


# Pydantic Models
class DatabaseCapability(BaseModel):
    """Database table capability."""

    id: int
    table_name: str
    category: str | None
    row_count: int
    total_columns: int
    columns: list[str]
    columns_with_data: list[str]
    columns_mostly_null: list[str]
    completeness_pct: int
    date_range_start: str | None
    date_range_end: str | None
    days_since_update: int | None
    freshness_status: str | None
    health_status: str
    last_scanned_at: str | None


class DatabaseCapabilitiesResponse(BaseModel):
    """Response for database capabilities list."""

    capabilities: list[DatabaseCapability]
    total: int
    summary: dict[str, Any] = Field(default_factory=dict)


class ScanResponse(BaseModel):
    """Response for scan operation."""

    status: str
    tables_scanned: int
    message: str


# API Endpoints
@router.get(
    "/projects/{project_id}/capabilities/database",
    response_model=DatabaseCapabilitiesResponse,
)
def list_database_capabilities(project_id: str) -> DatabaseCapabilitiesResponse:
    """List database table capabilities for a project.

    Args:
        project_id: The project ID

    Returns:
        List of database capabilities with summary
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT id, table_name, category, row_count, total_columns,
                       columns, columns_with_data, columns_mostly_null,
                       completeness_pct, date_range_start, date_range_end,
                       days_since_update, freshness_status, health_status,
                       last_scanned_at
                FROM scanner_database
                WHERE project_id = %s
                ORDER BY row_count DESC
                """,
            [project_id],
        )
        rows = cur.fetchall()

        if not rows:
            return DatabaseCapabilitiesResponse(
                capabilities=[],
                total=0,
                summary={"message": "No scan data. Run POST .../scan first."},
            )

        capabilities = []
        health_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        total_rows = 0

        for row in rows:
            cap = DatabaseCapability(
                id=row[0],
                table_name=row[1],
                category=row[2],
                row_count=row[3],
                total_columns=row[4],
                columns=row[5] if isinstance(row[5], list) else json.loads(row[5] or "[]"),
                columns_with_data=(
                    row[6] if isinstance(row[6], list) else json.loads(row[6] or "[]")
                ),
                columns_mostly_null=(
                    row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]")
                ),
                completeness_pct=row[8],
                date_range_start=str(row[9]) if row[9] else None,
                date_range_end=str(row[10]) if row[10] else None,
                days_since_update=row[11],
                freshness_status=row[12],
                health_status=row[13] or "unknown",
                last_scanned_at=row[14].isoformat() if row[14] else None,
            )
            capabilities.append(cap)

            # Build summary
            health = cap.health_status
            health_counts[health] = health_counts.get(health, 0) + 1

            cat = cap.category or "uncategorized"
            category_counts[cat] = category_counts.get(cat, 0) + 1

            total_rows += cap.row_count

        return DatabaseCapabilitiesResponse(
            capabilities=capabilities,
            total=len(capabilities),
            summary={
                "total_tables": len(capabilities),
                "total_rows": total_rows,
                "by_health": health_counts,
                "by_category": category_counts,
            },
        )


@router.post(
    "/projects/{project_id}/capabilities/database/scan",
    response_model=ScanResponse,
)
def scan_database_capabilities(project_id: str) -> ScanResponse:
    """Trigger a database capability scan for a project.

    Args:
        project_id: The project ID

    Returns:
        Scan result with count of tables scanned
    """
    db_url = get_project_db_url(project_id)
    if not db_url:
        raise HTTPException(
            status_code=400,
            detail=f"No database URL configured for project {project_id}",
        )

    scanner = DatabaseScanner(project_id, db_url)
    capabilities = scanner.scan()
    saved = scanner.save(capabilities)

    return ScanResponse(
        status="complete",
        tables_scanned=saved,
        message=f"Scanned {saved} tables for {project_id}",
    )


@router.get("/projects/{project_id}/capabilities/database/{table_name}")
def get_database_capability(project_id: str, table_name: str) -> DatabaseCapability:
    """Get details for a specific table capability.

    Args:
        project_id: The project ID
        table_name: The table name

    Returns:
        Table capability details
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT id, table_name, category, row_count, total_columns,
                       columns, columns_with_data, columns_mostly_null,
                       completeness_pct, date_range_start, date_range_end,
                       days_since_update, freshness_status, health_status,
                       last_scanned_at
                FROM scanner_database
                WHERE project_id = %s AND table_name = %s
                """,
            [project_id, table_name],
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Table not found")

        return DatabaseCapability(
            id=row[0],
            table_name=row[1],
            category=row[2],
            row_count=row[3],
            total_columns=row[4],
            columns=row[5] if isinstance(row[5], list) else json.loads(row[5] or "[]"),
            columns_with_data=(
                row[6] if isinstance(row[6], list) else json.loads(row[6] or "[]")
            ),
            columns_mostly_null=(
                row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]")
            ),
            completeness_pct=row[8],
            date_range_start=str(row[9]) if row[9] else None,
            date_range_end=str(row[10]) if row[10] else None,
            days_since_update=row[11],
            freshness_status=row[12],
            health_status=row[13] or "unknown",
            last_scanned_at=row[14].isoformat() if row[14] else None,
        )


# ============================================================
# API Scanner Endpoints
# ============================================================


class APICapability(BaseModel):
    """API endpoint capability."""

    id: int
    endpoint_path: str
    http_method: str
    category: str | None
    route_file: str | None
    function_name: str | None
    depends_on_tables: list[str]
    frontend_callers: list[str]
    health_status: str
    last_scanned_at: str | None


class APICapabilitiesResponse(BaseModel):
    """Response for API capabilities list."""

    capabilities: list[APICapability]
    total: int
    summary: dict[str, Any] = Field(default_factory=dict)


class APIScanResponse(BaseModel):
    """Response for API scan operation."""

    status: str
    endpoints_scanned: int
    message: str


@router.get(
    "/projects/{project_id}/capabilities/api",
    response_model=APICapabilitiesResponse,
)
def list_api_capabilities(project_id: str) -> APICapabilitiesResponse:
    """List API endpoint capabilities for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, endpoint_path, http_method, category, route_file,
                   function_name, depends_on_tables, frontend_callers,
                   health_status, last_scanned_at
            FROM scanner_api
            WHERE project_id = %s
            ORDER BY endpoint_path
            """,
            [project_id],
        )
        rows = cur.fetchall()

        if not rows:
            return APICapabilitiesResponse(
                capabilities=[],
                total=0,
                summary={"message": "No scan data. Run POST .../scan first."},
            )

        capabilities = []
        health_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        method_counts: dict[str, int] = {}

        for row in rows:
            cap = APICapability(
                id=row[0],
                endpoint_path=row[1],
                http_method=row[2],
                category=row[3],
                route_file=row[4],
                function_name=row[5],
                depends_on_tables=(
                    row[6] if isinstance(row[6], list) else json.loads(row[6] or "[]")
                ),
                frontend_callers=(
                    row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]")
                ),
                health_status=row[8] or "unknown",
                last_scanned_at=row[9].isoformat() if row[9] else None,
            )
            capabilities.append(cap)

            health = cap.health_status
            health_counts[health] = health_counts.get(health, 0) + 1

            cat = cap.category or "uncategorized"
            category_counts[cat] = category_counts.get(cat, 0) + 1

            method = cap.http_method
            method_counts[method] = method_counts.get(method, 0) + 1

        return APICapabilitiesResponse(
            capabilities=capabilities,
            total=len(capabilities),
            summary={
                "total_endpoints": len(capabilities),
                "by_health": health_counts,
                "by_category": category_counts,
                "by_method": method_counts,
            },
        )


@router.post(
    "/projects/{project_id}/capabilities/api/scan",
    response_model=APIScanResponse,
)
def scan_api_capabilities(project_id: str) -> APIScanResponse:
    """Trigger an API capability scan for a project."""
    root_path, backend_dir = get_project_paths(project_id)
    if not root_path:
        raise HTTPException(
            status_code=400,
            detail=f"No root path configured for project {project_id}",
        )

    scanner = APIScanner(project_id, root_path, backend_dir)
    capabilities = scanner.scan()
    saved = scanner.save(capabilities)

    return APIScanResponse(
        status="complete",
        endpoints_scanned=saved,
        message=f"Scanned {saved} endpoints for {project_id}",
    )


# ============================================================
# Celery Scanner Endpoints
# ============================================================


class CeleryCapability(BaseModel):
    """Celery task capability."""

    id: int
    task_name: str
    category: str | None
    task_path: str | None
    function_name: str | None
    schedule_description: str | None
    schedule_crontab: str | None
    schedule_interval_seconds: int | None
    last_run_at: str | None
    success_count_7d: int
    failure_count_7d: int
    success_rate_pct: int | None
    populates_tables: list[str]
    reads_from_tables: list[str]
    depends_on_tasks: list[str]
    called_by: list[str]
    health_status: str
    last_scanned_at: str | None


class CeleryCapabilitiesResponse(BaseModel):
    """Response for Celery capabilities list."""

    capabilities: list[CeleryCapability]
    total: int
    summary: dict[str, Any] = Field(default_factory=dict)


class CeleryScanResponse(BaseModel):
    """Response for Celery scan operation."""

    status: str
    tasks_scanned: int
    message: str


@router.get(
    "/projects/{project_id}/capabilities/celery",
    response_model=CeleryCapabilitiesResponse,
)
def list_celery_capabilities(project_id: str) -> CeleryCapabilitiesResponse:
    """List Celery task capabilities for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, task_name, category, task_path, function_name,
                   schedule_description, schedule_crontab, schedule_interval_seconds,
                   last_run_at, success_count_7d, failure_count_7d, success_rate_pct,
                   populates_tables, reads_from_tables, depends_on_tasks, called_by,
                   health_status, last_scanned_at
            FROM scanner_celery
            WHERE project_id = %s
            ORDER BY task_name
            """,
            [project_id],
        )
        rows = cur.fetchall()

        if not rows:
            return CeleryCapabilitiesResponse(
                capabilities=[],
                total=0,
                summary={"message": "No scan data. Run POST .../scan first."},
            )

        capabilities = []
        health_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}

        for row in rows:
            cap = CeleryCapability(
                id=row[0],
                task_name=row[1],
                category=row[2],
                task_path=row[3],
                function_name=row[4],
                schedule_description=row[5],
                schedule_crontab=row[6],
                schedule_interval_seconds=row[7],
                last_run_at=row[8].isoformat() if row[8] else None,
                success_count_7d=row[9] or 0,
                failure_count_7d=row[10] or 0,
                success_rate_pct=row[11],
                populates_tables=(
                    row[12] if isinstance(row[12], list) else json.loads(row[12] or "[]")
                ),
                reads_from_tables=(
                    row[13] if isinstance(row[13], list) else json.loads(row[13] or "[]")
                ),
                depends_on_tasks=(
                    row[14] if isinstance(row[14], list) else json.loads(row[14] or "[]")
                ),
                called_by=(
                    row[15] if isinstance(row[15], list) else json.loads(row[15] or "[]")
                ),
                health_status=row[16] or "unknown",
                last_scanned_at=row[17].isoformat() if row[17] else None,
            )
            capabilities.append(cap)

            health = cap.health_status
            health_counts[health] = health_counts.get(health, 0) + 1

            cat = cap.category or "uncategorized"
            category_counts[cat] = category_counts.get(cat, 0) + 1

        return CeleryCapabilitiesResponse(
            capabilities=capabilities,
            total=len(capabilities),
            summary={
                "total_tasks": len(capabilities),
                "by_health": health_counts,
                "by_category": category_counts,
            },
        )


@router.post(
    "/projects/{project_id}/capabilities/celery/scan",
    response_model=CeleryScanResponse,
)
def scan_celery_capabilities(project_id: str) -> CeleryScanResponse:
    """Trigger a Celery capability scan for a project."""
    root_path, backend_dir, beat_endpoint = get_project_celery_config(project_id)
    if not root_path:
        raise HTTPException(
            status_code=400,
            detail=f"No root path configured for project {project_id}",
        )

    scanner = CeleryScanner(project_id, root_path, backend_dir, beat_endpoint)
    capabilities = scanner.scan()
    saved = scanner.save(capabilities)

    return CeleryScanResponse(
        status="complete",
        tasks_scanned=saved,
        message=f"Scanned {saved} tasks for {project_id}",
    )
