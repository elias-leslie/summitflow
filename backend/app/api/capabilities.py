"""Capabilities scanner API endpoints.

Provides REST API for database/API/Celery capability scanning:
- GET /api/projects/{id}/capabilities/database - list DB capabilities
- POST /api/projects/{id}/capabilities/database/scan - trigger scan
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
