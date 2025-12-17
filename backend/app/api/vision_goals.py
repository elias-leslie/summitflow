"""Vision Goals router - endpoints for vision goals management.

This module provides REST API endpoints for vision goals:
- GET /projects/{project_id}/vision-goals - List all goals with feature counts
- GET /projects/{project_id}/vision-goals/{code} - Get single goal with linked features
- GET /projects/{project_id}/vision-goals/summary - Get summary stats per goal
- POST /projects/{project_id}/vision-goals - Create new goal
- PATCH /projects/{project_id}/vision-goals/{code} - Update goal
- DELETE /projects/{project_id}/vision-goals/{code} - Delete goal (if no features linked)

Extracted from portfolio-ai/backend/app/api/capabilities/vision_goals_router.py
Changes from source:
  - Added project_id path parameter to all endpoints
  - Uses get_connection() context manager
  - Feature queries filter by project_id
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..logging_config import get_logger
from ..storage.connection import get_connection

logger = get_logger(__name__)

router = APIRouter(prefix="/projects/{project_id}/vision-goals", tags=["vision-goals"])


class VisionGoal(BaseModel):
    """Model for a vision goal."""

    code: str  # VG-INTEL, VG-AUTO, etc.
    name: str
    description: str | None = None
    category: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class VisionGoalWithStats(VisionGoal):
    """Vision goal with linked feature statistics."""

    feature_count: int = 0
    criteria_passed: int = 0
    criteria_total: int = 0
    pass_rate: float = 0.0


class VisionGoalCreate(BaseModel):
    """Request model for creating a vision goal."""

    code: str
    name: str
    description: str | None = None
    category: str | None = None


class VisionGoalUpdate(BaseModel):
    """Request model for updating a vision goal."""

    name: str | None = None
    description: str | None = None
    category: str | None = None


@router.get("/", response_model=list[VisionGoalWithStats])
async def get_vision_goals(project_id: str) -> list[VisionGoalWithStats]:
    """Get all vision goals with feature and criteria statistics for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Get all vision goals (shared lookup table)
            cur.execute(
                """
                SELECT code, name, description, category, created_at, updated_at
                FROM vision_goals
                ORDER BY code
                """
            )
            goals = cur.fetchall()

            # Get feature counts and criteria stats per goal (project-scoped)
            cur.execute(
                """
                SELECT
                    unnest(vision_goals) as goal_code,
                    COUNT(DISTINCT feature_id) as feature_count,
                    SUM(jsonb_array_length(COALESCE(acceptance_criteria, '[]'))) as criteria_total,
                    SUM((
                        SELECT COUNT(*)
                        FROM jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                        WHERE c->>'passed' = 'true'
                    )) as criteria_passed
                FROM feature_capabilities
                WHERE project_id = %s
                  AND vision_goals IS NOT NULL
                  AND array_length(vision_goals, 1) > 0
                GROUP BY goal_code
                """,
                (project_id,),
            )
            stats = cur.fetchall()

            # Build stats lookup
            stats_map: dict[Any, dict[str, int]] = {
                row[0]: {
                    "feature_count": int(row[1] or 0),
                    "criteria_total": int(row[2] or 0),
                    "criteria_passed": int(row[3] or 0),
                }
                for row in stats
            }

            result: list[VisionGoalWithStats] = []
            for g in goals:
                code_val = cast(str, g[0])
                s = stats_map.get(
                    code_val, {"feature_count": 0, "criteria_total": 0, "criteria_passed": 0}
                )
                criteria_total = s["criteria_total"]
                criteria_passed = s["criteria_passed"]
                pass_rate = criteria_passed / criteria_total if criteria_total > 0 else 0.0

                created_at_val = g[4]
                updated_at_val = g[5]

                result.append(
                    VisionGoalWithStats(
                        code=code_val,
                        name=cast(str, g[1]),
                        description=cast(str | None, g[2]),
                        category=cast(str | None, g[3]),
                        created_at=cast(datetime, created_at_val).isoformat()
                        if created_at_val
                        else None,
                        updated_at=cast(datetime, updated_at_val).isoformat()
                        if updated_at_val
                        else None,
                        feature_count=s["feature_count"],
                        criteria_total=criteria_total,
                        criteria_passed=criteria_passed,
                        pass_rate=round(pass_rate, 3),
                    )
                )

            return result

    except Exception as e:
        logger.error("get_vision_goals_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/summary", response_model=dict[str, Any])
async def get_vision_goals_summary(project_id: str) -> dict[str, Any]:
    """Get summary statistics for all vision goals in a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Get goal count
            cur.execute("SELECT COUNT(*) FROM vision_goals")
            goal_count_row = cur.fetchone()
            goal_count = int(cast(int, goal_count_row[0])) if goal_count_row else 0

            # Get per-goal stats (project-scoped)
            cur.execute(
                """
                SELECT
                    vg.code,
                    vg.name,
                    COUNT(DISTINCT fc.feature_id) as feature_count,
                    COALESCE(SUM(jsonb_array_length(COALESCE(fc.acceptance_criteria, '[]'))), 0) as criteria_total,
                    COALESCE(SUM((
                        SELECT COUNT(*)
                        FROM jsonb_array_elements(COALESCE(fc.acceptance_criteria, '[]')) c
                        WHERE c->>'passed' = 'true'
                    )), 0) as criteria_passed
                FROM vision_goals vg
                LEFT JOIN feature_capabilities fc
                    ON vg.code = ANY(fc.vision_goals) AND fc.project_id = %s
                GROUP BY vg.code, vg.name
                ORDER BY vg.code
                """,
                (project_id,),
            )
            stats = cur.fetchall()

            goals: list[dict[str, Any]] = []
            for row in stats:
                criteria_total_val = int(row[3] or 0)
                criteria_passed_val = int(row[4] or 0)
                pass_rate = (
                    criteria_passed_val / criteria_total_val if criteria_total_val > 0 else 0.0
                )
                goals.append(
                    {
                        "code": row[0],
                        "name": row[1],
                        "feature_count": row[2],
                        "criteria_total": criteria_total_val,
                        "criteria_passed": criteria_passed_val,
                        "pass_rate": round(pass_rate, 3),
                    }
                )

            return {
                "project_id": project_id,
                "total_goals": goal_count,
                "goals": goals,
            }

    except Exception as e:
        logger.error("get_vision_goals_summary_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{code}", response_model=dict[str, Any])
async def get_vision_goal(project_id: str, code: str) -> dict[str, Any]:
    """Get a single vision goal with linked features for a project."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Get the goal
            cur.execute(
                """
                SELECT code, name, description, category, created_at, updated_at
                FROM vision_goals
                WHERE code = %s
                """,
                (code,),
            )
            goal = cur.fetchone()

            if not goal:
                raise HTTPException(status_code=404, detail=f"Vision goal {code} not found")

            # Get linked features (project-scoped)
            cur.execute(
                """
                SELECT
                    feature_id,
                    name,
                    passes,
                    jsonb_array_length(COALESCE(acceptance_criteria, '[]')) as criteria_total,
                    (
                        SELECT COUNT(*)
                        FROM jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                        WHERE c->>'passed' = 'true'
                    ) as criteria_passed
                FROM feature_capabilities
                WHERE project_id = %s AND %s = ANY(vision_goals)
                ORDER BY feature_id
                """,
                (project_id, code),
            )
            features = cur.fetchall()

            created_at_val = goal[4]
            updated_at_val = goal[5]

            return {
                "code": goal[0],
                "name": goal[1],
                "description": goal[2],
                "category": goal[3],
                "created_at": cast(datetime, created_at_val).isoformat()
                if created_at_val
                else None,
                "updated_at": cast(datetime, updated_at_val).isoformat()
                if updated_at_val
                else None,
                "feature_count": len(features),
                "features": [
                    {
                        "feature_id": f[0],
                        "name": f[1],
                        "passes": f[2],
                        "criteria_total": f[3],
                        "criteria_passed": f[4],
                    }
                    for f in features
                ],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_vision_goal_failed", project_id=project_id, code=code, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{code}/details", response_model=list[dict[str, Any]])
async def get_vision_goal_details(project_id: str, code: str) -> list[dict[str, Any]]:
    """Get detailed content for a vision goal (objectives, features, success criteria)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Verify goal exists
            cur.execute(
                "SELECT code FROM vision_goals WHERE code = %s",
                (code,),
            )
            goal_check = cur.fetchone()

            if not goal_check:
                raise HTTPException(status_code=404, detail=f"Vision goal {code} not found")

            # Get details from vision_goal_details table
            cur.execute(
                """
                SELECT id, goal_code, detail_type, content, order_num, metadata
                FROM vision_goal_details
                WHERE goal_code = %s
                ORDER BY detail_type, order_num
                """,
                (code,),
            )
            details = cur.fetchall()

            return [
                {
                    "id": row[0],
                    "goal_code": row[1],
                    "detail_type": row[2],
                    "content": row[3],
                    "order_num": row[4],
                    "metadata": row[5],
                }
                for row in details
            ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_vision_goal_details_failed", project_id=project_id, code=code, error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/", response_model=dict[str, Any])
async def create_vision_goal(project_id: str, goal: VisionGoalCreate) -> dict[str, Any]:
    """Create a new vision goal."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vision_goals (code, name, description, category)
                VALUES (%s, %s, %s, %s)
                RETURNING code, name, description, category
                """,
                (goal.code, goal.name, goal.description, goal.category),
            )
            result = cur.fetchone()
            conn.commit()

            logger.info(
                "vision_goal_created", project_id=project_id, code=goal.code, name=goal.name
            )

            if not result:
                raise HTTPException(status_code=500, detail="Failed to create vision goal")

            return {
                "status": "created",
                "code": result[0],
                "name": result[1],
                "description": result[2],
                "category": result[3],
            }

    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=409, detail=f"Vision goal {goal.code} already exists"
            ) from e
        logger.error("create_vision_goal_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/{code}", response_model=dict[str, Any])
async def update_vision_goal(
    project_id: str, code: str, update: VisionGoalUpdate
) -> dict[str, Any]:
    """Update a vision goal."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Build update query dynamically
            updates = []
            values: list[str | None] = []
            if update.name is not None:
                updates.append("name = %s")
                values.append(update.name)
            if update.description is not None:
                updates.append("description = %s")
                values.append(update.description)
            if update.category is not None:
                updates.append("category = %s")
                values.append(update.category)

            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")

            updates.append("updated_at = NOW()")
            values.append(code)

            query = f"""
                UPDATE vision_goals
                SET {", ".join(updates)}
                WHERE code = %s
                RETURNING code, name, description, category
            """

            cur.execute(query, tuple(values))
            result = cur.fetchone()
            conn.commit()

            if not result:
                raise HTTPException(status_code=404, detail=f"Vision goal {code} not found")

            logger.info("vision_goal_updated", project_id=project_id, code=code)

            return {
                "status": "updated",
                "code": result[0],
                "name": result[1],
                "description": result[2],
                "category": result[3],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_vision_goal_failed", project_id=project_id, code=code, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{code}", response_model=dict[str, Any])
async def delete_vision_goal(project_id: str, code: str) -> dict[str, Any]:
    """Delete a vision goal (only if no features are linked in any project)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Check if any features are linked (across all projects)
            cur.execute(
                """
                SELECT COUNT(*)
                FROM feature_capabilities
                WHERE %s = ANY(vision_goals)
                """,
                (code,),
            )
            linked_count_row = cur.fetchone()

            if not linked_count_row:
                raise HTTPException(status_code=500, detail="Failed to check linked features")

            linked_count = int(cast(int, linked_count_row[0]))

            if linked_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete: {linked_count} features are linked to {code}",
                )

            cur.execute(
                """
                DELETE FROM vision_goals
                WHERE code = %s
                RETURNING code
                """,
                (code,),
            )
            result = cur.fetchone()
            conn.commit()

            if not result:
                raise HTTPException(status_code=404, detail=f"Vision goal {code} not found")

            logger.info("vision_goal_deleted", project_id=project_id, code=code)

            return {"status": "deleted", "code": code}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_vision_goal_failed", project_id=project_id, code=code, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e
