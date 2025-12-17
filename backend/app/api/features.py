"""Features API - Feature capability tracking for projects.

This module provides REST API endpoints for feature capabilities:
- GET /projects/{project_id}/features - List all features with filtering
- GET /projects/{project_id}/features/{feature_id} - Get single feature detail
- GET /projects/{project_id}/features/summary - Get feature statistics
- POST /projects/{project_id}/features - Add new feature
- DELETE /projects/{project_id}/features/{feature_id} - Delete a feature and its subtasks
- PATCH /projects/{project_id}/features/{feature_id}/verified - Mark verification timestamp
- PATCH /projects/{project_id}/features/{feature_id}/status - Update work status
- PATCH /projects/{project_id}/features/{feature_id}/effort - Update effort estimate
- PATCH /projects/{project_id}/features/{feature_id}/priority - Update priority
- PATCH /projects/{project_id}/features/{feature_id}/layers - Update verification layers
- PATCH /projects/{project_id}/features/{feature_id}/acceptance-criteria - Update acceptance criteria

Dependency endpoints:
- GET /projects/{project_id}/features/{feature_id}/dependencies - List feature dependencies
- POST /projects/{project_id}/features/{feature_id}/dependencies - Add dependency
- DELETE /projects/{project_id}/features/{feature_id}/dependencies/{depends_on_feature_id} - Remove dependency

Vision goal endpoints:
- PATCH /projects/{project_id}/features/{feature_id}/vision-goals - Update vision goals

Verification endpoints:
- POST /projects/{project_id}/features/verify-all - Run verification on all automatable criteria
- POST /projects/{project_id}/features/verify-batch - Verify a batch of criteria
- POST /projects/{project_id}/features/{feature_id}/verify - Queue verification for a feature
- GET /projects/{project_id}/features/verification-summary - Get verification statistics
- GET /projects/{project_id}/features/criteria/failing - List failing criteria
- GET /projects/{project_id}/features/criteria/pending - List pending criteria
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from ..storage.connection import get_connection

router = APIRouter()


# Pydantic models for request/response
class FeatureCreate(BaseModel):
    """Request model for creating a new feature."""

    feature_id: str | None = None  # Auto-generated if not provided
    name: str
    category: str
    description: str | None = None


class QuickFeatureCreate(BaseModel):
    """Request model for creating a quick debug feature."""

    url: str  # The page URL being captured
    description: str | None = None  # Optional description

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format."""
        from urllib.parse import urlparse

        if not v:
            raise ValueError("URL is required")
        parsed = urlparse(v)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Invalid URL format")
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must be http or https")
        return v


class FeatureLayersUpdate(BaseModel):
    """Request model for updating feature verification layers."""

    layers: list[str]  # e.g., ["UI", "API", "Backend", "DB", "Tasks"]


class FeatureLayerResultUpdate(BaseModel):
    """Request model for updating a single layer's verification result."""

    layer: str  # e.g., "UI", "API", "Backend", "DB", "Tasks"
    passed: bool
    evidence: str | None = None


class AcceptanceCriterion(BaseModel):
    """Model for a single acceptance criterion."""

    id: str  # e.g., "ac-001"
    criterion: str  # What needs to be true
    verification: str  # How to verify (curl command, screenshot, etc.)
    type: str  # api, ui, db, backend, quality, content
    passed: bool | None = None  # null = not checked, true/false = result
    # Verification tracking fields (added for auto-verification)
    verified_at: str | None = None  # ISO timestamp of last verification
    verification_output: str | None = None  # Actual output (truncated)


class FeatureResponse(BaseModel):
    """Response model for a single feature."""

    id: int | None = None
    project_id: str
    feature_id: str
    name: str
    category: str | None
    description: str | None
    layers: list[str] = []  # Verification layers: Frontend, Backend, UI, API, DB, Tasks
    layer_results: dict[
        str, dict[str, Any]
    ] = {}  # Per-layer verification: {"UI": {"passed": true}}
    total_tasks: int = 0  # From DB
    completed_tasks: int = 0  # From DB
    completion_pct: int = 0
    health_status: str  # active or orphaned (based on tasks)
    last_verified_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # Spec-driven fields
    priority: int | None = None  # User override (1-5), null = auto
    effective_priority: int = 5  # Calculated priority (1-5)
    acceptance_criteria: list[AcceptanceCriterion] = []  # Testable criteria
    vision_goals: list[str] = []  # Links to VISION.md goals


class FeaturesListResponse(BaseModel):
    """Response model for list of features."""

    features: list[FeatureResponse]
    total: int
    filtered: int


class FeatureSummaryResponse(BaseModel):
    """Response model for feature statistics."""

    total: int
    category_breakdown: dict[str, int]
    health_breakdown: dict[str, int]


# Helper functions
def _feature_to_response(f: dict[str, Any]) -> FeatureResponse:
    """Convert feature dict from database to response model."""
    # Convert acceptance_criteria from JSONB to list of AcceptanceCriterion
    raw_criteria = f.get("acceptance_criteria", [])
    acceptance_criteria = [
        AcceptanceCriterion(
            id=c.get("id", ""),
            criterion=c.get("criterion", ""),
            verification=c.get("verification", ""),
            type=c.get("type", ""),
            passed=c.get("passed"),
            verified_at=c.get("verified_at"),
            verification_output=c.get("verification_output"),
        )
        for c in raw_criteria
        if isinstance(c, dict)
    ]

    return FeatureResponse(
        id=f.get("id"),
        project_id=f["project_id"],
        feature_id=f["feature_id"],
        name=f["name"],
        category=f.get("category"),
        description=f.get("description"),
        layers=f.get("layers", []),
        layer_results=f.get("layer_results", {}),
        total_tasks=f.get("total_tasks", 0),
        completed_tasks=f.get("completed_tasks", 0),
        completion_pct=f.get("completion_pct", 0),
        health_status=f.get("health_status", "unknown"),
        last_verified_at=(f["last_verified_at"].isoformat() if f.get("last_verified_at") else None),
        created_at=f["created_at"].isoformat() if f.get("created_at") else None,
        updated_at=f["updated_at"].isoformat() if f.get("updated_at") else None,
        priority=f.get("priority"),
        effective_priority=f.get("effective_priority", 5),
        acceptance_criteria=acceptance_criteria,
        vision_goals=f.get("vision_goals", []),
    )


def _get_next_feature_id(project_id: str) -> str:
    """Generate next feature ID for a project (e.g., FEAT-001, FEAT-002)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT feature_id
                FROM feature_capabilities
                WHERE project_id = %s
                  AND feature_id ~ '^FEAT-[0-9]+$'
                ORDER BY feature_id DESC
                LIMIT 1
                """,
            (project_id,),
        )
        row = cur.fetchone()

    if row:
        # Extract number and increment
        last_id = row[0]
        num = int(last_id.split("-")[1])
        return f"FEAT-{num + 1:03d}"
    else:
        return "FEAT-001"


# Endpoints
@router.get("/projects/{project_id}/features", response_model=FeaturesListResponse)
async def get_features(
    project_id: str,
    category: str | None = Query(None, description="Filter by category"),
    health_status: str | None = Query(None, description="Filter by health: active, orphaned"),
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    offset: int = Query(0, ge=0, description="Results offset"),
) -> FeaturesListResponse:
    """Get paginated list of features for a project.

    Query params:
        - category: Filter by category (Dashboard, Watchlist, etc.)
        - health_status: Filter by health (active|orphaned)
        - limit: Results per page (default 50, max 500)
        - offset: Results offset for pagination
    """
    # TODO: Add FeatureScanner integration when available
    # For now, query database directly

    with get_connection() as conn, conn.cursor() as cur:
        # Build query with filters
        where_clauses = ["project_id = %s"]
        params: list[Any] = [project_id]

        if category:
            where_clauses.append("category = %s")
            params.append(category)

        if health_status:
            where_clauses.append("health_status = %s")
            params.append(health_status)

        where_sql = " AND ".join(where_clauses)

        # Get total count
        cur.execute(
            f"SELECT COUNT(*) FROM feature_capabilities WHERE {where_sql}",
            tuple(params),
        )
        total = cur.fetchone()[0] if cur.rowcount > 0 else 0

        # Get paginated results
        params.extend([limit, offset])
        cur.execute(
            f"""
                SELECT id, project_id, feature_id, name, category, description,
                       verification_layers, layer_results, priority, acceptance_criteria,
                       vision_goals, last_verified_at, created_at, updated_at
                FROM feature_capabilities
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
            tuple(params),
        )
        rows = cur.fetchall()

    # Convert to response format
    features_response = []
    for row in rows:
        feature_dict = {
            "id": row[0],
            "project_id": row[1],
            "feature_id": row[2],
            "name": row[3],
            "category": row[4],
            "description": row[5],
            "layers": row[6] or [],
            "layer_results": row[7] or {},
            "priority": row[8],
            "acceptance_criteria": row[9] or [],
            "vision_goals": row[10] or [],
            "last_verified_at": row[11],
            "created_at": row[12],
            "updated_at": row[13],
            "total_tasks": 0,  # TODO: Calculate from feature_tasks
            "completed_tasks": 0,  # TODO: Calculate from feature_tasks
            "completion_pct": 0,
            "health_status": "active",  # TODO: Calculate based on tasks
            "effective_priority": row[8] or 5,
        }
        features_response.append(_feature_to_response(feature_dict))

    return FeaturesListResponse(
        features=features_response,
        total=total,
        filtered=len(features_response),
    )


@router.get("/projects/{project_id}/features/summary", response_model=FeatureSummaryResponse)
async def get_features_summary(project_id: str) -> FeatureSummaryResponse:
    """Get feature statistics summary for a project.

    Returns counts by category and health status.
    """
    # TODO: Add FeatureScanner integration when available

    with get_connection() as conn, conn.cursor() as cur:
        # Total count
        cur.execute(
            "SELECT COUNT(*) FROM feature_capabilities WHERE project_id = %s",
            (project_id,),
        )
        total = cur.fetchone()[0] if cur.rowcount > 0 else 0

        # Category breakdown
        cur.execute(
            """
                SELECT category, COUNT(*)
                FROM feature_capabilities
                WHERE project_id = %s
                GROUP BY category
                """,
            (project_id,),
        )
        category_breakdown = {row[0]: row[1] for row in cur.fetchall()}

        # Health breakdown - TODO: calculate based on tasks
        health_breakdown = {"active": total, "orphaned": 0}

    return FeatureSummaryResponse(
        total=total,
        category_breakdown=category_breakdown,
        health_breakdown=health_breakdown,
    )


# =========================================================================
# Verification Summary Endpoints (MUST come before /{feature_id} routes)
# =========================================================================


class VerificationSummary(BaseModel):
    """Response model for verification summary."""

    total_criteria: int
    passed: int
    failed: int
    pending: int
    by_type: dict[str, dict[str, int]]
    last_run_at: str | None


@router.get(
    "/projects/{project_id}/features/verification-summary", response_model=VerificationSummary
)
async def get_verification_summary(project_id: str) -> VerificationSummary:
    """Get summary statistics for acceptance criteria verification."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Get all criteria counts
            cur.execute(
                """
                    SELECT
                        SUM(jsonb_array_length(COALESCE(acceptance_criteria, '[]'))) as total,
                        SUM((
                            SELECT COUNT(*)
                            FROM jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                            WHERE c->>'passed' = 'true'
                        )) as passed,
                        SUM((
                            SELECT COUNT(*)
                            FROM jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                            WHERE c->>'passed' = 'false'
                        )) as failed
                    FROM feature_capabilities
                    WHERE project_id = %s
                    """,
                (project_id,),
            )
            row = cur.fetchone()

            total_val: int = int(row[0]) if row and row[0] else 0
            passed_val: int = int(row[1]) if row and row[1] else 0
            failed_val: int = int(row[2]) if row and row[2] else 0
            pending_val: int = total_val - passed_val - failed_val

            # Get by-type breakdown
            cur.execute(
                """
                    SELECT
                        c->>'type' as type,
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE c->>'passed' = 'true') as passed,
                        COUNT(*) FILTER (WHERE c->>'passed' = 'false') as failed
                    FROM feature_capabilities,
                         jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                    WHERE project_id = %s
                    GROUP BY c->>'type'
                    """,
                (project_id,),
            )
            type_rows = cur.fetchall()

            by_type: dict[str, dict[str, int]] = {}
            for r in type_rows:
                ctype = str(r[0]) if r[0] else "unknown"
                type_total = int(r[1]) if r[1] else 0
                type_passed = int(r[2]) if r[2] else 0
                type_failed = int(r[3]) if r[3] else 0
                by_type[ctype] = {
                    "total": type_total,
                    "passed": type_passed,
                    "failed": type_failed,
                    "pending": type_total - type_passed - type_failed,
                }

            # Get last run timestamp - TODO: add criteria_verification_runs table
            last_run_at: str | None = None

            return VerificationSummary(
                total_criteria=total_val,
                passed=passed_val,
                failed=failed_val,
                pending=pending_val,
                by_type=by_type,
                last_run_at=last_run_at,
            )

    except Exception:
        return VerificationSummary(
            total_criteria=0,
            passed=0,
            failed=0,
            pending=0,
            by_type={},
            last_run_at=None,
        )


@router.get("/projects/{project_id}/features/criteria/failing", response_model=list[dict[str, Any]])
async def get_failing_criteria(project_id: str) -> list[dict[str, Any]]:
    """Get all failing acceptance criteria for quick triage."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                    SELECT
                        fc.feature_id,
                        fc.name as feature_name,
                        c->>'id' as criterion_id,
                        c->>'criterion' as criterion,
                        c->>'verification' as verification,
                        c->>'verification_output' as verification_output,
                        c->>'verified_at' as verified_at
                    FROM feature_capabilities fc,
                         jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                    WHERE fc.project_id = %s
                      AND c->>'passed' = 'false'
                    ORDER BY c->>'verified_at' DESC NULLS LAST
                    LIMIT 100
                    """,
                (project_id,),
            )
            rows = cur.fetchall()

        return [
            {
                "feature_id": r[0],
                "feature_name": r[1],
                "criterion_id": r[2],
                "criterion": r[3],
                "verification": r[4],
                "verification_output": r[5],
                "failed_at": r[6],
            }
            for r in rows
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/projects/{project_id}/features/criteria/pending", response_model=list[dict[str, Any]])
async def get_pending_criteria(
    project_id: str,
    type_filter: str | None = Query(None, alias="type", description="Filter by type"),
) -> list[dict[str, Any]]:
    """Get all pending (unverified) acceptance criteria."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            if type_filter:
                cur.execute(
                    """
                        SELECT
                            fc.feature_id,
                            c->>'id' as criterion_id,
                            c->>'criterion' as criterion,
                            c->>'verification' as verification,
                            c->>'type' as type
                        FROM feature_capabilities fc,
                             jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                        WHERE fc.project_id = %s
                          AND c->>'passed' IS NULL
                          AND c->>'type' = %s
                        ORDER BY fc.feature_id, c->>'id'
                        LIMIT 100
                        """,
                    (project_id, type_filter),
                )
            else:
                cur.execute(
                    """
                        SELECT
                            fc.feature_id,
                            c->>'id' as criterion_id,
                            c->>'criterion' as criterion,
                            c->>'verification' as verification,
                            c->>'type' as type
                        FROM feature_capabilities fc,
                             jsonb_array_elements(COALESCE(acceptance_criteria, '[]')) c
                        WHERE fc.project_id = %s
                          AND c->>'passed' IS NULL
                        ORDER BY fc.feature_id, c->>'id'
                        LIMIT 100
                        """,
                    (project_id,),
                )
            rows = cur.fetchall()

        return [
            {
                "feature_id": r[0],
                "criterion_id": r[1],
                "criterion": r[2],
                "verification": r[3],
                "type": r[4],
            }
            for r in rows
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/projects/{project_id}/features/verify-all", response_model=dict[str, Any])
async def verify_all_features(
    project_id: str,
    type_filter: str | None = Query(None, description="Filter by type: api, test, ui"),
    limit: int | None = Query(None, description="Limit number of criteria to verify"),
) -> dict[str, Any]:
    """Trigger verification of all auto-verifiable criteria.

    TODO: Queue this as a Celery task when task system is integrated.
    """
    # TODO: Import and call verify_all_acceptance_criteria Celery task
    raise HTTPException(
        status_code=501,
        detail="Bulk verification not yet implemented. Will be added with Celery integration.",
    )


@router.post("/projects/{project_id}/features/verify-batch", response_model=dict[str, Any])
async def verify_batch(project_id: str, feature_ids: list[str]) -> dict[str, Any]:
    """Trigger verification for multiple features.

    TODO: Queue this as a Celery task when task system is integrated.
    """
    # TODO: Import and call verify_criteria_batch Celery task
    raise HTTPException(
        status_code=501,
        detail="Batch verification not yet implemented. Will be added with Celery integration.",
    )


# =========================================================================
# Feature Detail and Update Endpoints
# =========================================================================


@router.get("/projects/{project_id}/features/{feature_id}", response_model=FeatureResponse)
async def get_feature(project_id: str, feature_id: str) -> FeatureResponse:
    """Get single feature by ID.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
    """
    # TODO: Add FeatureScanner integration when available

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT id, project_id, feature_id, name, category, description,
                       verification_layers, layer_results, priority, acceptance_criteria,
                       vision_goals, last_verified_at, created_at, updated_at
                FROM feature_capabilities
                WHERE project_id = %s AND feature_id = %s
                """,
            (project_id, feature_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=404, detail=f"Feature {feature_id} not found in project {project_id}"
        )

    feature_dict = {
        "id": row[0],
        "project_id": row[1],
        "feature_id": row[2],
        "name": row[3],
        "category": row[4],
        "description": row[5],
        "layers": row[6] or [],
        "layer_results": row[7] or {},
        "priority": row[8],
        "acceptance_criteria": row[9] or [],
        "vision_goals": row[10] or [],
        "last_verified_at": row[11],
        "created_at": row[12],
        "updated_at": row[13],
        "total_tasks": 0,  # TODO: Calculate from feature_tasks
        "completed_tasks": 0,  # TODO: Calculate from feature_tasks
        "completion_pct": 0,
        "health_status": "active",  # TODO: Calculate based on tasks
        "effective_priority": row[8] or 5,
    }

    return _feature_to_response(feature_dict)


@router.post("/projects/{project_id}/features", response_model=dict[str, Any])
async def create_feature(project_id: str, feature: FeatureCreate) -> dict[str, Any]:
    """Create a new feature.

    Args:
        project_id: Project ID
        feature: Feature data (name, category, description)
    """
    # TODO: Add FeatureScanner integration when available

    # Auto-generate feature_id if not provided
    feature_id = feature.feature_id or _get_next_feature_id(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        # Check if feature_id already exists
        cur.execute(
            "SELECT id FROM feature_capabilities WHERE project_id = %s AND feature_id = %s",
            (project_id, feature_id),
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=409,
                detail=f"Feature {feature_id} already exists in project {project_id}",
            )

        # Insert new feature
        cur.execute(
            """
                INSERT INTO feature_capabilities
                    (project_id, feature_id, name, category, description, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                RETURNING feature_id
                """,
            (project_id, feature_id, feature.name, feature.category, feature.description),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(status_code=500, detail="Failed to create feature")

    return {
        "status": "created",
        "project_id": project_id,
        "feature_id": feature_id,
        "name": feature.name,
        "category": feature.category,
    }


@router.post("/projects/{project_id}/features/quick", response_model=dict[str, Any])
async def create_quick_feature(project_id: str, request: QuickFeatureCreate) -> dict[str, Any]:
    """Create a quick debug feature for evidence capture.

    This endpoint auto-creates a feature with:
    - ID: DBG-MMDD-HHMMSS
    - Category: Debug
    - Single acceptance criterion: "Evidence capture from {url}"

    Args:
        project_id: Project ID
        request: URL and optional description

    Returns:
        feature_id, criterion_id, and name for immediate use
    """
    # Generate timestamp-based feature ID (short format)
    now = datetime.now()
    feature_id = f"DBG-{now.strftime('%m%d-%H%M%S')}"

    # Extract path from URL for display name
    from urllib.parse import urlparse

    parsed = urlparse(request.url)
    path = parsed.path or "/"
    name = f"Debug: {path}"

    # Create single acceptance criterion
    criterion_id = "ac-001"
    acceptance_criteria = [
        {
            "id": criterion_id,
            "criterion": f"Evidence capture from {path}",
            "verification": f"screenshot {path}",
            "type": "ui",
            "passed": None,
        }
    ]

    description = request.description or f"Quick debug feature created for {path}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_capabilities
                    (project_id, feature_id, name, category, description, acceptance_criteria, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
                """,
                (
                    project_id,
                    feature_id,
                    name,
                    "Debug",
                    description,
                    json.dumps(acceptance_criteria),
                ),
            )
            conn.commit()

    return {
        "feature_id": feature_id,
        "criterion_id": criterion_id,
        "name": name,
        "created": True,
    }


@router.delete("/projects/{project_id}/features/{feature_id}", response_model=dict[str, Any])
async def delete_feature(project_id: str, feature_id: str) -> dict[str, Any]:
    """Delete a feature and all its associated data.

    This permanently removes:
    - The feature record
    - All subtasks (feature_tasks)
    - All dependencies (feature_dependencies)
    - All vision goal mappings (feature_vision_goal_mappings)
    - All artifacts

    Args:
        project_id: Project ID
        feature_id: Feature ID to delete (e.g., FEAT-001)

    Returns:
        Confirmation of deletion with feature_id

    Warning:
        This action is irreversible. Use with caution.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Check feature exists
        cur.execute(
            "SELECT id, name FROM feature_capabilities WHERE project_id = %s AND feature_id = %s",
            (project_id, feature_id),
        )
        feature_check = cur.fetchone()

        if not feature_check:
            raise HTTPException(
                status_code=404,
                detail=f"Feature {feature_id} not found in project {project_id}",
            )

        feature_db_id = feature_check[0]
        feature_name = feature_check[1]

        # Delete in correct order due to FK constraints
        # 1. Delete artifacts (feature_id is VARCHAR in artifacts table)
        cur.execute(
            "DELETE FROM artifacts WHERE project_id = %s AND feature_id = %s",
            (project_id, feature_id),
        )

        # 2. Delete subtasks
        cur.execute(
            "DELETE FROM feature_tasks WHERE feature_id = %s",
            (feature_db_id,),
        )

        # 3. Delete dependencies (both directions)
        cur.execute(
            "DELETE FROM feature_dependencies WHERE feature_id = %s OR depends_on_id = %s",
            (feature_db_id, feature_db_id),
        )

        # 4. Delete vision goal mappings
        cur.execute(
            "DELETE FROM feature_vision_goal_mappings WHERE feature_id = %s",
            (feature_db_id,),
        )

        # 5. Delete the feature itself
        cur.execute(
            "DELETE FROM feature_capabilities WHERE id = %s",
            (feature_db_id,),
        )

        conn.commit()

    return {
        "status": "deleted",
        "project_id": project_id,
        "feature_id": feature_id,
        "name": feature_name,
    }


@router.patch(
    "/projects/{project_id}/features/{feature_id}/verified", response_model=dict[str, Any]
)
async def mark_feature_verified(project_id: str, feature_id: str) -> dict[str, Any]:
    """Mark feature verification timestamp.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
    """
    # TODO: Add FeatureScanner integration when available

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE feature_capabilities
                SET last_verified_at = NOW(), updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                RETURNING feature_id
                """,
            (project_id, feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(
            status_code=404, detail=f"Feature {feature_id} not found in project {project_id}"
        )

    return {
        "status": "verified",
        "project_id": project_id,
        "feature_id": feature_id,
        "last_verified_at": "now",
    }


@router.patch("/projects/{project_id}/features/{feature_id}/layers", response_model=dict[str, Any])
async def update_feature_layers(
    project_id: str, feature_id: str, update: FeatureLayersUpdate
) -> dict[str, Any]:
    """Update the verification layers for a feature.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        update: New layers list
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE feature_capabilities
                SET verification_layers = %s, updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                RETURNING feature_id
                """,
            (update.verification_layers, project_id, feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(
            status_code=404, detail=f"Feature {feature_id} not found in project {project_id}"
        )

    return {
        "status": "updated",
        "project_id": project_id,
        "feature_id": feature_id,
        "layers": update.verification_layers,
    }


@router.patch(
    "/projects/{project_id}/features/{feature_id}/layer-result", response_model=dict[str, Any]
)
async def update_feature_layer_result(
    project_id: str, feature_id: str, update: FeatureLayerResultUpdate
) -> dict[str, Any]:
    """Update a single layer's verification result.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        update: Layer name, passed status, and evidence
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Update the specific layer in layer_results JSONB
        layer_data = json.dumps(
            {update.layer: {"passed": update.passed, "evidence": update.evidence}}
        )
        cur.execute(
            """
                UPDATE feature_capabilities
                SET layer_results = layer_results || %s::jsonb,
                    updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                RETURNING feature_id, layer_results
                """,
            (layer_data, project_id, feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(
            status_code=404, detail=f"Feature {feature_id} not found in project {project_id}"
        )

    return {
        "status": "updated",
        "project_id": project_id,
        "feature_id": feature_id,
        "layer": update.layer,
        "passed": update.passed,
        "evidence": update.evidence,
        "layer_results": result[1],
    }


# =========================================================================
# Spec-Driven Endpoints (priority, acceptance criteria, vision goals)
# =========================================================================


class FeaturePriorityUpdate(BaseModel):
    """Request model for updating feature priority."""

    priority: int | None  # 1-5 for user override, null to auto-calculate


@router.patch(
    "/projects/{project_id}/features/{feature_id}/priority", response_model=dict[str, Any]
)
async def update_feature_priority(
    project_id: str, feature_id: str, update: FeaturePriorityUpdate
) -> dict[str, Any]:
    """Update the priority for a feature.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        update: New priority (1-5) or null for auto-calculate
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE feature_capabilities
                SET priority = %s, updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                RETURNING feature_id, priority
                """,
            (update.priority, project_id, feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(
            status_code=404, detail=f"Feature {feature_id} not found in project {project_id}"
        )

    return {
        "status": "updated",
        "project_id": project_id,
        "feature_id": feature_id,
        "priority": update.priority,
    }


class AcceptanceCriteriaUpdate(BaseModel):
    """Request model for updating acceptance criteria."""

    acceptance_criteria: list[dict[str, Any]]  # Full replacement of criteria array


@router.patch(
    "/projects/{project_id}/features/{feature_id}/acceptance-criteria",
    response_model=dict[str, Any],
)
async def update_feature_acceptance_criteria(
    project_id: str, feature_id: str, update: AcceptanceCriteriaUpdate
) -> dict[str, Any]:
    """Update the acceptance criteria for a feature.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        update: New acceptance criteria array
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE feature_capabilities
                SET acceptance_criteria = %s::jsonb, updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                RETURNING feature_id, acceptance_criteria
                """,
            (json.dumps(update.acceptance_criteria), project_id, feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(
            status_code=404, detail=f"Feature {feature_id} not found in project {project_id}"
        )

    return {
        "status": "updated",
        "project_id": project_id,
        "feature_id": feature_id,
        "acceptance_criteria": result[1],
    }


class AcceptanceCriterionPassedUpdate(BaseModel):
    """Request model for updating a single criterion's passed status."""

    passed: bool | None = None  # true, false, or null to reset
    evidence: str | None = None  # Evidence for the pass/fail decision
    criterion_type: str | None = None  # ui, api, db, backend
    verification_url: str | None = None  # URL for verification


@router.patch(
    "/projects/{project_id}/features/{feature_id}/acceptance-criteria/{criterion_id}",
    response_model=dict[str, Any],
)
async def update_acceptance_criterion_passed(
    project_id: str, feature_id: str, criterion_id: str, update: AcceptanceCriterionPassedUpdate
) -> dict[str, Any]:
    """Update the passed status of a single acceptance criterion.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        criterion_id: Criterion ID within the feature (e.g., ac-001)
        update: New passed status and optional evidence
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get current acceptance_criteria
        cur.execute(
            """
                SELECT acceptance_criteria
                FROM feature_capabilities
                WHERE project_id = %s AND feature_id = %s
                """,
            (project_id, feature_id),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Feature {feature_id} not found in project {project_id}",
            )

        criteria_raw: Any = row[0] if row[0] else []
        # Ensure we have a list of dicts
        criteria: list[dict[str, Any]] = criteria_raw if isinstance(criteria_raw, list) else []

        # Find and update the specific criterion
        found = False
        for c in criteria:
            if isinstance(c, dict) and c.get("id") == criterion_id:
                if update.passed is not None:
                    c["passed"] = update.passed
                if update.evidence is not None:
                    c["evidence"] = update.evidence
                if update.criterion_type is not None:
                    c["type"] = update.criterion_type
                if update.verification_url is not None:
                    c["verification"] = update.verification_url
                found = True
                break

        if not found:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found in feature {feature_id}",
            )

        # Update the database
        cur.execute(
            """
                UPDATE feature_capabilities
                SET acceptance_criteria = %s::jsonb, updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                """,
            (json.dumps(criteria), project_id, feature_id),
        )
        conn.commit()

    return {
        "status": "updated",
        "project_id": project_id,
        "feature_id": feature_id,
        "criterion_id": criterion_id,
        "passed": update.passed,
        "evidence": update.evidence,
    }


class VisionGoalsUpdate(BaseModel):
    """Request model for updating vision goals."""

    vision_goals: list[str]  # List of VISION.md goal identifiers


@router.patch(
    "/projects/{project_id}/features/{feature_id}/vision-goals", response_model=dict[str, Any]
)
async def update_feature_vision_goals(
    project_id: str, feature_id: str, update: VisionGoalsUpdate
) -> dict[str, Any]:
    """Update the vision goals for a feature.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        update: New vision goals list
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE feature_capabilities
                SET vision_goals = %s, updated_at = NOW()
                WHERE project_id = %s AND feature_id = %s
                RETURNING feature_id, vision_goals
                """,
            (update.vision_goals, project_id, feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(
            status_code=404, detail=f"Feature {feature_id} not found in project {project_id}"
        )

    return {
        "status": "updated",
        "project_id": project_id,
        "feature_id": feature_id,
        "vision_goals": result[1],
    }


# =========================================================================
# Feature Dependencies Endpoints
# =========================================================================


class DependencyCreate(BaseModel):
    """Request model for creating a dependency."""

    depends_on_feature_id: str  # The feature this one depends on
    dependency_type: str = "blocks"  # blocks, soft, related
    notes: str | None = None


class DependencyResponse(BaseModel):
    """Response model for a dependency."""

    id: int
    feature_id: str
    depends_on_feature_id: str
    depends_on_name: str
    depends_on_passes: bool | None
    dependency_type: str
    notes: str | None
    is_satisfied: bool


@router.get(
    "/projects/{project_id}/features/{feature_id}/dependencies",
    response_model=list[DependencyResponse],
)
async def get_feature_dependencies(project_id: str, feature_id: str) -> list[DependencyResponse]:
    """Get all dependencies for a feature (what it depends on)."""
    with get_connection() as conn, conn.cursor() as cur:
        # First verify feature exists
        cur.execute(
            "SELECT id FROM feature_capabilities WHERE project_id = %s AND feature_id = %s",
            (project_id, feature_id),
        )
        feature_check = cur.fetchone()

        if not feature_check:
            raise HTTPException(
                status_code=404,
                detail=f"Feature {feature_id} not found in project {project_id}",
            )

        # Get dependencies - TODO: create feature_dependency_view for SummitFlow
        # For now, query directly
        cur.execute(
            """
                SELECT fd.id, fc1.feature_id, fc2.feature_id, fc2.name,
                       NULL as depends_on_passes, fd.dependency_type, fd.notes,
                       false as is_satisfied
                FROM feature_dependencies fd
                JOIN feature_capabilities fc1 ON fd.feature_id = fc1.id
                JOIN feature_capabilities fc2 ON fd.depends_on_id = fc2.id
                WHERE fc1.project_id = %s AND fc1.feature_id = %s
                """,
            (project_id, feature_id),
        )
        rows = cur.fetchall()

    return [
        DependencyResponse(
            id=int(row[0]) if row[0] else 0,
            feature_id=str(row[1]) if row[1] else "",
            depends_on_feature_id=str(row[2]) if row[2] else "",
            depends_on_name=str(row[3]) if row[3] else "",
            depends_on_passes=bool(row[4]) if row[4] is not None else None,
            dependency_type=str(row[5]) if row[5] else "",
            notes=str(row[6]) if row[6] else None,
            is_satisfied=bool(row[7]) if row[7] is not None else False,
        )
        for row in rows
    ]


@router.post(
    "/projects/{project_id}/features/{feature_id}/dependencies", response_model=dict[str, Any]
)
async def add_feature_dependency(
    project_id: str, feature_id: str, dependency: DependencyCreate
) -> dict[str, Any]:
    """Add a dependency to a feature.

    dependency_type values:
    - blocks: Hard dependency - depends_on must complete first
    - soft: Nice to have completed first
    - related: Just related, no ordering requirement
    """
    valid_types = {"blocks", "soft", "related"}
    if dependency.dependency_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dependency_type '{dependency.dependency_type}'. Must be one of: {valid_types}",
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get both feature IDs
            cur.execute(
                "SELECT id FROM feature_capabilities WHERE project_id = %s AND feature_id = %s",
                (project_id, feature_id),
            )
            feature_row = cur.fetchone()

            cur.execute(
                "SELECT id FROM feature_capabilities WHERE project_id = %s AND feature_id = %s",
                (project_id, dependency.depends_on_feature_id),
            )
            depends_on_row = cur.fetchone()

            if not feature_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Feature {feature_id} not found in project {project_id}",
                )
            if not depends_on_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Depends-on feature {dependency.depends_on_feature_id} not found in project {project_id}",
                )

            # Insert dependency
            cur.execute(
                """
                INSERT INTO feature_dependencies (feature_id, depends_on_id, dependency_type, notes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (feature_id, depends_on_id) DO UPDATE
                SET dependency_type = EXCLUDED.dependency_type, notes = EXCLUDED.notes
                """,
                (feature_row[0], depends_on_row[0], dependency.dependency_type, dependency.notes),
            )
            conn.commit()

    return {
        "status": "created",
        "project_id": project_id,
        "feature_id": feature_id,
        "depends_on": dependency.depends_on_feature_id,
        "dependency_type": dependency.dependency_type,
    }


@router.delete("/projects/{project_id}/features/{feature_id}/dependencies/{depends_on_feature_id}")
async def remove_feature_dependency(
    project_id: str, feature_id: str, depends_on_feature_id: str
) -> dict[str, Any]:
    """Remove a dependency from a feature."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                DELETE FROM feature_dependencies
                WHERE feature_id = (
                    SELECT id FROM feature_capabilities
                    WHERE project_id = %s AND feature_id = %s
                )
                AND depends_on_id = (
                    SELECT id FROM feature_capabilities
                    WHERE project_id = %s AND feature_id = %s
                )
                RETURNING id
                """,
            (project_id, feature_id, project_id, depends_on_feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Dependency {feature_id} -> {depends_on_feature_id} not found in project {project_id}",
        )

    return {
        "status": "deleted",
        "project_id": project_id,
        "feature_id": feature_id,
        "depends_on": depends_on_feature_id,
    }


# =========================================================================
# Feature-Specific Verification Endpoint
# =========================================================================


@router.post("/projects/{project_id}/features/{feature_id}/verify", response_model=dict[str, Any])
async def verify_feature(project_id: str, feature_id: str) -> dict[str, Any]:
    """Trigger verification of all criteria for a feature.

    TODO: Queue this as a Celery task when task system is integrated.
    """
    # TODO: Import and call verify_feature_criteria Celery task
    raise HTTPException(
        status_code=501,
        detail="Feature verification not yet implemented. Will be added with Celery integration.",
    )
