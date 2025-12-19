"""Features storage layer - Feature and acceptance criteria CRUD operations.

This module provides data access for features and their acceptance criteria.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .connection import get_connection


def get_feature(project_id: str, feature_id: str) -> dict[str, Any] | None:
    """Get a single feature by project_id and feature_id.

    Returns:
        Feature dict with all columns, or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, feature_id, name, category, description,
                   verification_layers, layer_results, priority, acceptance_criteria,
                   vision_goals, health_status, status, last_verified_at,
                   created_at, updated_at
            FROM feature_capabilities
            WHERE project_id = %s AND feature_id = %s
            """,
            (project_id, feature_id),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "feature_id": row[2],
        "name": row[3],
        "category": row[4],
        "description": row[5],
        "verification_layers": row[6] or [],
        "layer_results": row[7] or {},
        "priority": row[8],
        "acceptance_criteria": row[9] or [],
        "vision_goals": row[10] or [],
        "health_status": row[11],
        "status": row[12],
        "last_verified_at": row[13],
        "created_at": row[14],
        "updated_at": row[15],
    }


def get_feature_by_db_id(feature_db_id: int) -> dict[str, Any] | None:
    """Get a single feature by database ID.

    Returns:
        Feature dict with all columns, or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, feature_id, name, category, description,
                   verification_layers, layer_results, priority, acceptance_criteria,
                   vision_goals, health_status, status, last_verified_at,
                   created_at, updated_at
            FROM feature_capabilities
            WHERE id = %s
            """,
            (feature_db_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "feature_id": row[2],
        "name": row[3],
        "category": row[4],
        "description": row[5],
        "verification_layers": row[6] or [],
        "layer_results": row[7] or {},
        "priority": row[8],
        "acceptance_criteria": row[9] or [],
        "vision_goals": row[10] or [],
        "health_status": row[11],
        "status": row[12],
        "last_verified_at": row[13],
        "created_at": row[14],
        "updated_at": row[15],
    }


# =========================================================================
# Acceptance Criteria Operations
# =========================================================================


def get_criteria(project_id: str, feature_id: str) -> list[dict[str, Any]]:
    """Get all acceptance criteria for a feature.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)

    Returns:
        List of criterion dicts, empty if feature not found or no criteria.
    """
    feature = get_feature(project_id, feature_id)
    if not feature:
        return []
    return feature.get("acceptance_criteria", [])


def add_criterion(
    project_id: str,
    feature_id: str,
    criterion: dict[str, Any],
) -> dict[str, Any] | None:
    """Add a new acceptance criterion to a feature.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        criterion: Criterion dict with at least 'id' and 'description'.
            Structure: {
                "id": "ac-001",
                "description": "Description of what needs to be true",
                "passes": false,  # Optional, defaults to false
                "verified_at": null,  # Optional
                "evidence_id": null  # Optional
            }

    Returns:
        The added criterion dict, or None if feature not found.

    Raises:
        ValueError: If criterion with same ID already exists.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get current criteria
        cur.execute(
            """
            SELECT acceptance_criteria
            FROM feature_capabilities
            WHERE project_id = %s AND feature_id = %s
            """,
            (project_id, feature_id),
        )
        row = cur.fetchone()

        if row is None:
            return None

        criteria: list[dict[str, Any]] = row[0] if row[0] else []

        # Check for duplicate ID
        criterion_id = criterion.get("id")
        for c in criteria:
            if c.get("id") == criterion_id:
                raise ValueError(f"Criterion with ID '{criterion_id}' already exists")

        # Ensure required fields
        new_criterion = {
            "id": criterion_id,
            "description": criterion.get("description", ""),
            "passes": criterion.get("passes", False),
            "verified_at": criterion.get("verified_at"),
            "evidence_id": criterion.get("evidence_id"),
        }

        # Add any extra fields from input
        for key, value in criterion.items():
            if key not in new_criterion:
                new_criterion[key] = value

        criteria.append(new_criterion)

        # Update database
        cur.execute(
            """
            UPDATE feature_capabilities
            SET acceptance_criteria = %s::jsonb, updated_at = NOW()
            WHERE project_id = %s AND feature_id = %s
            """,
            (json.dumps(criteria), project_id, feature_id),
        )
        conn.commit()

    return new_criterion


def update_criterion_status(
    project_id: str,
    feature_id: str,
    criterion_id: str,
    passes: bool,
    evidence_id: str | None = None,
) -> dict[str, Any] | None:
    """Update the passes status of a single acceptance criterion.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        criterion_id: Criterion ID within the feature (e.g., ac-001)
        passes: True if criterion is met, False otherwise
        evidence_id: Optional evidence ID to link

    Returns:
        The updated criterion dict, or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get current criteria
        cur.execute(
            """
            SELECT acceptance_criteria
            FROM feature_capabilities
            WHERE project_id = %s AND feature_id = %s
            """,
            (project_id, feature_id),
        )
        row = cur.fetchone()

        if row is None:
            return None

        criteria: list[dict[str, Any]] = row[0] if row[0] else []

        # Find and update the criterion
        updated_criterion = None
        for c in criteria:
            if c.get("id") == criterion_id:
                c["passes"] = passes
                c["verified_at"] = datetime.now(timezone.utc).isoformat()
                if evidence_id:
                    c["evidence_id"] = evidence_id
                updated_criterion = c
                break

        if not updated_criterion:
            return None

        # Update database
        cur.execute(
            """
            UPDATE feature_capabilities
            SET acceptance_criteria = %s::jsonb, updated_at = NOW()
            WHERE project_id = %s AND feature_id = %s
            """,
            (json.dumps(criteria), project_id, feature_id),
        )
        conn.commit()

    return updated_criterion


def delete_criterion(
    project_id: str,
    feature_id: str,
    criterion_id: str,
) -> bool:
    """Delete a criterion from a feature.

    Args:
        project_id: Project ID
        feature_id: Feature ID (e.g., FEAT-001)
        criterion_id: Criterion ID to delete (e.g., ac-001)

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get current criteria
        cur.execute(
            """
            SELECT acceptance_criteria
            FROM feature_capabilities
            WHERE project_id = %s AND feature_id = %s
            """,
            (project_id, feature_id),
        )
        row = cur.fetchone()

        if row is None:
            return False

        criteria: list[dict[str, Any]] = row[0] if row[0] else []

        # Find and remove the criterion
        original_len = len(criteria)
        criteria = [c for c in criteria if c.get("id") != criterion_id]

        if len(criteria) == original_len:
            return False  # Not found

        # Update database
        cur.execute(
            """
            UPDATE feature_capabilities
            SET acceptance_criteria = %s::jsonb, updated_at = NOW()
            WHERE project_id = %s AND feature_id = %s
            """,
            (json.dumps(criteria), project_id, feature_id),
        )
        conn.commit()

    return True


def update_feature_status(
    project_id: str,
    feature_id: str,
    status: str,
) -> bool:
    """Update feature status (backlog, in_progress, review, done).

    Args:
        project_id: Project ID
        feature_id: Feature ID
        status: New status value

    Returns:
        True if updated, False if feature not found.
    """
    valid_statuses = {"backlog", "in_progress", "review", "done"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE feature_capabilities
            SET status = %s, updated_at = NOW()
            WHERE project_id = %s AND feature_id = %s
            RETURNING id
            """,
            (status, project_id, feature_id),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None
