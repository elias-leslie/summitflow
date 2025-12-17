"""Vision Content router - endpoints for VISION.md narrative content.

This module provides REST API endpoints for vision content:
- GET /projects/{project_id}/vision - Get all vision content (grouped by type)
- GET /projects/{project_id}/vision/mission - Get mission statement
- GET /projects/{project_id}/vision/narrative - Get vision narrative (what/why)
- GET /projects/{project_id}/vision/principles - Get core principles
- GET /projects/{project_id}/vision/success-metrics - Get success metrics
- GET /projects/{project_id}/vision/roadmap - Get roadmap phases
- GET /projects/{project_id}/vision/examples - Get principles in practice examples
- PATCH /projects/{project_id}/vision/content/{content_key} - Update any content by key
- PATCH /projects/{project_id}/vision/roadmap/{content_key} - Update roadmap phase status

Extracted from portfolio-ai/backend/app/api/capabilities/vision_content_router.py
Changes from source:
  - Added project_id path parameter to all endpoints
  - Uses get_connection() context manager
  - All queries filter by project_id
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..logging_config import get_logger
from ..storage.connection import get_connection

logger = get_logger(__name__)

router = APIRouter(prefix="/projects/{project_id}/vision", tags=["vision"])


class VisionContent(BaseModel):
    """Model for a piece of vision content."""

    id: int
    content_type: str
    content_key: str
    title: str | None = None
    content: str
    order_num: int = 0
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class VisionContentUpdate(BaseModel):
    """Request model for updating vision content."""

    title: str | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None
    order_num: int | None = None


class RoadmapStatusUpdate(BaseModel):
    """Request model for updating roadmap phase status."""

    status: str  # planned, in_progress, complete
    features: list[str] | None = None  # Optional list of feature IDs


@router.get("", response_model=dict[str, Any])
async def get_all_vision_content(project_id: str) -> dict[str, Any]:
    """Get all vision content grouped by type for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_type, content_key, title, content, order_num, metadata,
                       created_at, updated_at
                FROM vision_content
                WHERE project_id = %s
                ORDER BY content_type, order_num
                """,
                (project_id,),
            )
            rows = cur.fetchall()

            # Group by content_type
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                content_type = cast(str, row[1])
                if content_type not in grouped:
                    grouped[content_type] = []

                grouped[content_type].append(
                    {
                        "id": row[0],
                        "content_type": row[1],
                        "content_key": row[2],
                        "title": row[3],
                        "content": row[4],
                        "order_num": row[5],
                        "metadata": row[6],
                        "created_at": cast(datetime, row[7]).isoformat() if row[7] else None,
                        "updated_at": cast(datetime, row[8]).isoformat() if row[8] else None,
                    }
                )

            return {
                "project_id": project_id,
                "content_types": list(grouped.keys()),
                "content": grouped,
            }

    except Exception as e:
        logger.error("get_all_vision_content_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/mission", response_model=dict[str, Any])
async def get_mission_statement(project_id: str) -> dict[str, Any]:
    """Get the mission statement for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_key, title, content, metadata, created_at, updated_at
                FROM vision_content
                WHERE project_id = %s AND content_type = 'mission'
                ORDER BY order_num
                LIMIT 1
                """,
                (project_id,),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Mission statement not found")

            return {
                "id": row[0],
                "content_key": row[1],
                "title": row[2],
                "content": row[3],
                "metadata": row[4],
                "created_at": cast(datetime, row[5]).isoformat() if row[5] else None,
                "updated_at": cast(datetime, row[6]).isoformat() if row[6] else None,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_mission_statement_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/narrative", response_model=dict[str, Any])
async def get_vision_narrative(project_id: str) -> dict[str, Any]:
    """Get the vision narrative (what we're building and why) for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_key, title, content, metadata, created_at, updated_at
                FROM vision_content
                WHERE project_id = %s AND content_type = 'vision'
                ORDER BY order_num
                """,
                (project_id,),
            )
            rows = cur.fetchall()

            if not rows:
                raise HTTPException(status_code=404, detail="Vision narrative not found")

            return {
                "sections": [
                    {
                        "id": row[0],
                        "content_key": row[1],
                        "title": row[2],
                        "content": row[3],
                        "metadata": row[4],
                        "created_at": cast(datetime, row[5]).isoformat() if row[5] else None,
                        "updated_at": cast(datetime, row[6]).isoformat() if row[6] else None,
                    }
                    for row in rows
                ],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_vision_narrative_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/principles", response_model=dict[str, Any])
async def get_core_principles(project_id: str) -> dict[str, Any]:
    """Get the core principles for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_key, title, content, order_num, metadata, created_at, updated_at
                FROM vision_content
                WHERE project_id = %s AND content_type = 'principle'
                ORDER BY order_num
                """,
                (project_id,),
            )
            rows = cur.fetchall()

            return {
                "count": len(rows),
                "principles": [
                    {
                        "id": row[0],
                        "content_key": row[1],
                        "title": row[2],
                        "content": row[3],
                        "order_num": row[4],
                        "metadata": row[5],
                        "created_at": cast(datetime, row[6]).isoformat() if row[6] else None,
                        "updated_at": cast(datetime, row[7]).isoformat() if row[7] else None,
                    }
                    for row in rows
                ],
            }

    except Exception as e:
        logger.error("get_core_principles_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/success-metrics", response_model=dict[str, Any])
async def get_success_metrics(project_id: str) -> dict[str, Any]:
    """Get the success metrics targets for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_key, title, content, order_num, metadata, created_at, updated_at
                FROM vision_content
                WHERE project_id = %s AND content_type = 'success_metric'
                ORDER BY order_num
                """,
                (project_id,),
            )
            rows = cur.fetchall()

            return {
                "count": len(rows),
                "categories": [
                    {
                        "id": row[0],
                        "content_key": row[1],
                        "title": row[2],
                        "content": row[3],
                        "order_num": row[4],
                        "metrics": cast(dict[str, Any], row[5]).get("metrics", [])
                        if row[5]
                        else [],
                        "created_at": cast(datetime, row[6]).isoformat() if row[6] else None,
                        "updated_at": cast(datetime, row[7]).isoformat() if row[7] else None,
                    }
                    for row in rows
                ],
            }

    except Exception as e:
        logger.error("get_success_metrics_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/roadmap", response_model=dict[str, Any])
async def get_roadmap(project_id: str) -> dict[str, Any]:
    """Get the roadmap phases for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_key, title, content, order_num, metadata, created_at, updated_at
                FROM vision_content
                WHERE project_id = %s AND content_type = 'roadmap_phase'
                ORDER BY order_num
                """,
                (project_id,),
            )
            rows = cur.fetchall()

            return {
                "count": len(rows),
                "phases": [
                    {
                        "id": row[0],
                        "content_key": row[1],
                        "title": row[2],
                        "content": row[3],
                        "phase_number": row[4],
                        "status": cast(dict[str, Any], row[5]).get("status", "unknown")
                        if row[5]
                        else "unknown",
                        "features": cast(dict[str, Any], row[5]).get("features", [])
                        if row[5]
                        else [],
                        "created_at": cast(datetime, row[6]).isoformat() if row[6] else None,
                        "updated_at": cast(datetime, row[7]).isoformat() if row[7] else None,
                    }
                    for row in rows
                ],
            }

    except Exception as e:
        logger.error("get_roadmap_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/examples", response_model=dict[str, Any])
async def get_principles_in_practice(project_id: str) -> dict[str, Any]:
    """Get the principles in practice examples for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_key, title, content, order_num, metadata, created_at, updated_at
                FROM vision_content
                WHERE project_id = %s AND content_type = 'example'
                ORDER BY order_num
                """,
                (project_id,),
            )
            rows = cur.fetchall()

            return {
                "count": len(rows),
                "examples": [
                    {
                        "id": row[0],
                        "content_key": row[1],
                        "title": row[2],
                        "content": row[3],
                        "order_num": row[4],
                        "principles_applied": cast(dict[str, Any], row[5]).get(
                            "principles_applied", []
                        )
                        if row[5]
                        else [],
                        "created_at": cast(datetime, row[6]).isoformat() if row[6] else None,
                        "updated_at": cast(datetime, row[7]).isoformat() if row[7] else None,
                    }
                    for row in rows
                ],
            }

    except Exception as e:
        logger.error("get_principles_in_practice_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/closing", response_model=dict[str, Any])
async def get_closing_statement(project_id: str) -> dict[str, Any]:
    """Get the closing/north star statement for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content_key, title, content, metadata, created_at, updated_at
                FROM vision_content
                WHERE project_id = %s AND content_type = 'closing'
                ORDER BY order_num
                LIMIT 1
                """,
                (project_id,),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Closing statement not found")

            return {
                "id": row[0],
                "content_key": row[1],
                "title": row[2],
                "content": row[3],
                "metadata": row[4],
                "created_at": cast(datetime, row[5]).isoformat() if row[5] else None,
                "updated_at": cast(datetime, row[6]).isoformat() if row[6] else None,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_closing_statement_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/context", response_model=dict[str, Any])
async def get_vision_context(project_id: str) -> dict[str, Any]:
    """Get full vision context for slash commands.

    Returns mission, principles, and key points in a format
    optimized for AI command consumption.
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Get mission
            cur.execute(
                """
                SELECT content FROM vision_content
                WHERE project_id = %s AND content_type = 'mission' LIMIT 1
                """,
                (project_id,),
            )
            mission = cur.fetchone()

            # Get principles
            cur.execute(
                """
                SELECT title, content FROM vision_content
                WHERE project_id = %s AND content_type = 'principle'
                ORDER BY order_num
                """,
                (project_id,),
            )
            principles = cur.fetchall()

            # Get vision goals with criteria progress
            cur.execute(
                """
                SELECT
                    vg.code,
                    vg.name,
                    vg.description,
                    COUNT(DISTINCT fc.feature_id) as feature_count,
                    COALESCE(SUM((
                        SELECT COUNT(*) FROM jsonb_array_elements(COALESCE(fc.acceptance_criteria, '[]')) c
                        WHERE c->>'passed' = 'true'
                    )), 0) as criteria_passed,
                    COALESCE(SUM(jsonb_array_length(COALESCE(fc.acceptance_criteria, '[]'))), 0) as criteria_total
                FROM vision_goals vg
                LEFT JOIN feature_capabilities fc
                    ON vg.code = ANY(fc.vision_goals) AND fc.project_id = %s
                GROUP BY vg.code, vg.name, vg.description
                ORDER BY vg.code
                """,
                (project_id,),
            )
            goals = cur.fetchall()

            return {
                "project_id": project_id,
                "mission": mission[0] if mission else None,
                "principles": [{"title": p[0], "content": p[1]} for p in principles],
                "goals": [
                    {
                        "code": g[0],
                        "name": g[1],
                        "description": g[2],
                        "feature_count": g[3],
                        "criteria_passed": g[4] or 0,
                        "criteria_total": g[5] or 0,
                        "progress_pct": round(
                            (cast(int, g[4]) or 0) / (cast(int, g[5]) or 1) * 100, 1
                        ),
                    }
                    for g in goals
                ],
            }

    except Exception as e:
        logger.error("get_vision_context_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


# =========================================================================
# Update Endpoints
# =========================================================================


@router.patch("/content/{content_key}", response_model=dict[str, Any])
async def update_vision_content(
    project_id: str, content_key: str, update: VisionContentUpdate
) -> dict[str, Any]:
    """Update any vision content by content_key."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Check content exists
            cur.execute(
                "SELECT id, content_type FROM vision_content WHERE project_id = %s AND content_key = %s",
                (project_id, content_key),
            )
            existing = cur.fetchone()

            if not existing:
                raise HTTPException(status_code=404, detail=f"Content '{content_key}' not found")

            # Build dynamic update
            updates: list[str] = []
            values: list[str | int] = []

            if update.title is not None:
                updates.append("title = %s")
                values.append(update.title)
            if update.content is not None:
                updates.append("content = %s")
                values.append(update.content)
            if update.metadata is not None:
                updates.append("metadata = %s::jsonb")
                values.append(json.dumps(update.metadata))
            if update.order_num is not None:
                updates.append("order_num = %s")
                values.append(update.order_num)

            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")

            updates.append("updated_at = NOW()")
            values.extend([project_id, content_key])

            query = f"""
                UPDATE vision_content
                SET {", ".join(updates)}
                WHERE project_id = %s AND content_key = %s
                RETURNING id, content_type, content_key, title, content, order_num, metadata
            """

            cur.execute(query, tuple(values))
            result = cur.fetchone()
            conn.commit()

            if not result:
                raise HTTPException(status_code=500, detail="Update failed")

            logger.info(
                "vision_content_updated",
                project_id=project_id,
                content_key=content_key,
                content_type=existing[1],
            )

            return {
                "status": "updated",
                "id": result[0],
                "content_type": result[1],
                "content_key": result[2],
                "title": result[3],
                "content": result[4],
                "order_num": result[5],
                "metadata": result[6],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "update_vision_content_failed",
            project_id=project_id,
            content_key=content_key,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/roadmap/{content_key}/status", response_model=dict[str, Any])
async def update_roadmap_status(
    project_id: str, content_key: str, update: RoadmapStatusUpdate
) -> dict[str, Any]:
    """Update roadmap phase status and optionally link features."""
    valid_statuses = {"planned", "in_progress", "complete"}
    if update.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{update.status}'. Must be one of: {valid_statuses}",
        )

    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Check roadmap phase exists
            cur.execute(
                """
                SELECT id, metadata FROM vision_content
                WHERE project_id = %s AND content_key = %s AND content_type = 'roadmap_phase'
                """,
                (project_id, content_key),
            )
            existing = cur.fetchone()

            if not existing:
                raise HTTPException(
                    status_code=404, detail=f"Roadmap phase '{content_key}' not found"
                )

            # Merge metadata
            current_metadata: dict[str, Any] = (
                cast(dict[str, Any], existing[1]) if existing[1] else {}
            )
            current_metadata["status"] = update.status
            if update.features is not None:
                current_metadata["features"] = update.features

            cur.execute(
                """
                UPDATE vision_content
                SET metadata = %s::jsonb, updated_at = NOW()
                WHERE project_id = %s AND content_key = %s
                RETURNING id, content_key, title, metadata
                """,
                (json.dumps(current_metadata), project_id, content_key),
            )
            result = cur.fetchone()
            conn.commit()

            if not result:
                raise HTTPException(status_code=500, detail="Update failed")

            logger.info(
                "roadmap_status_updated",
                project_id=project_id,
                content_key=content_key,
                status=update.status,
            )

            return {
                "status": "updated",
                "id": result[0],
                "content_key": result[1],
                "title": result[2],
                "phase_status": cast(dict[str, Any], result[3]).get("status")
                if result[3]
                else None,
                "features": cast(dict[str, Any], result[3]).get("features", [])
                if result[3]
                else [],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "update_roadmap_status_failed",
            project_id=project_id,
            content_key=content_key,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e
