"""Pattern application logic for the memory health checker.

Handles auto-applying approved patterns and promoting patterns to global scope.
"""

from __future__ import annotations

import logging
from typing import Any

from ...storage import memory as memory_storage
from ...storage.connection import get_connection
from ...storage.memory_utils import GLOBAL_SCOPE
from .types import MIN_CONFIDENCE_FOR_AUTO_APPLY

logger = logging.getLogger(__name__)


def get_approved_patterns(project_id: str) -> list[dict[str, Any]]:
    """Get patterns in 'approved' status waiting to be applied.

    Returns:
        List of approved patterns with id, title, confidence, content
    """
    patterns = memory_storage.list_patterns(
        project_id=project_id,
        status="approved",
        limit=100,
    )
    return [p for p in patterns if p.get("confidence", 0) >= MIN_CONFIDENCE_FOR_AUTO_APPLY]


def get_global_approved_patterns() -> list[dict[str, Any]]:
    """Get approved patterns from global scope (project_id IS NULL).

    Returns:
        List of approved global patterns with confidence >= MIN_CONFIDENCE_FOR_AUTO_APPLY
    """
    patterns = memory_storage.list_patterns(
        project_id=GLOBAL_SCOPE,
        status="approved",
        limit=100,
    )
    return [p for p in patterns if p.get("confidence", 0) >= MIN_CONFIDENCE_FOR_AUTO_APPLY]


def apply_approved_patterns(project_id: str | None, patterns: list[dict[str, Any]]) -> int:
    """Mark approved patterns as 'applied' in the database.

    With progressive disclosure, patterns are served from the database via
    /context/expand API - no file writes needed. This function just updates
    the status in the database.

    Args:
        project_id: Project ID (or None for global patterns) - used for logging
        patterns: List of approved patterns to mark as applied

    Returns:
        Number of patterns successfully marked as applied
    """
    if not patterns:
        return 0

    applied_count = 0

    for pattern in patterns:
        pattern_id = pattern.get("id")
        if not pattern_id:
            continue

        try:
            # Just mark as applied in the database - no file writes
            memory_storage.mark_pattern_applied(pattern_id)
            applied_count += 1
            logger.info(f"Marked pattern as applied: {pattern_id}: {pattern.get('title')}")
        except Exception as e:
            logger.error(f"Failed to mark pattern {pattern_id} as applied: {e}")
            continue

    return applied_count


def apply_global_patterns() -> int:
    """Mark approved global patterns as 'applied' in the database.

    Returns:
        Number of global patterns marked as applied
    """
    global_patterns = get_global_approved_patterns()
    if not global_patterns:
        return 0

    applied = apply_approved_patterns(None, global_patterns)
    if applied > 0:
        logger.info(f"Marked {applied} global patterns as applied (database only)")
    return applied


def check_auto_promotion_candidates() -> list[dict[str, Any]]:
    """Find patterns eligible for auto-promotion to global scope.

    Criteria for auto-promotion:
    - Confidence >= 0.95
    - Applied (status='applied')
    - Same pattern title exists and is applied in 2+ different projects

    Returns:
        List of patterns eligible for auto-promotion
    """
    candidates = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.project_id, p.title, p.content, p.confidence
            FROM learned_patterns p
            WHERE p.status = 'applied'
              AND p.confidence >= 0.95
              AND p.project_id IS NOT NULL
              AND NOT EXISTS (
                -- Skip if already promoted to global
                SELECT 1 FROM learned_patterns g
                WHERE g.project_id IS NULL
                  AND g.title = p.title
              )
            """
        )
        rows = cur.fetchall()

        # Group by title to find those applied in 2+ projects
        title_projects: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            pattern = {
                "id": row[0],
                "project_id": row[1],
                "title": row[2],
                "content": row[3],
                "confidence": row[4],
            }
            title = pattern["title"]
            if title not in title_projects:
                title_projects[title] = []
            title_projects[title].append(pattern)

        # Find patterns with same title in 2+ projects
        for _title, patterns in title_projects.items():
            unique_projects = set(p["project_id"] for p in patterns)
            if len(unique_projects) >= 2:
                # Pick the highest confidence version
                best = max(patterns, key=lambda p: p["confidence"])
                candidates.append(
                    {
                        **best,
                        "project_count": len(unique_projects),
                    }
                )

    return candidates


def auto_promote_patterns() -> int:
    """Auto-promote eligible patterns to global scope.

    Returns:
        Number of patterns promoted
    """
    from .pattern_service import PatternService

    candidates = check_auto_promotion_candidates()
    if not candidates:
        return 0

    promoted = 0
    for pattern in candidates:
        try:
            # Use the source project's service to promote
            service = PatternService(project_id=pattern["project_id"])
            global_pattern = service.promote_to_global(pattern["id"])

            logger.info(
                f"auto_promoted_pattern: "
                f"id={pattern['id']} title='{pattern['title']}' "
                f"projects={pattern['project_count']} "
                f"global_id={global_pattern.get('id')}"
            )
            promoted += 1

        except ValueError as e:
            logger.warning(f"Auto-promotion failed for {pattern['id']}: {e}")
            continue

    return promoted
