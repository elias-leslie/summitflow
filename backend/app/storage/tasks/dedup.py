"""Tasks storage - Deduplication helpers for task creation.

This module provides semantic matching to prevent duplicate tasks.
"""

from __future__ import annotations

import re
from typing import Any

from ..connection import get_connection


def task_exists_for_file(project_id: str, file_path: str) -> bool:
    """Check if a task already exists that targets a specific file.

    Used for deduplication when auto-generating tasks from Explorer scans.

    Args:
        project_id: Project to check
        file_path: File path to look for in task description or title

    Returns:
        True if a pending/running task exists for this file
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM tasks
                WHERE project_id = %s
                AND status IN ('pending', 'running', 'paused', 'blocked', 'pr_created', 'ai_reviewing')
                AND (
                    description LIKE %s
                    OR title LIKE %s
                )
            )
            """,
            (project_id, f"%{file_path}%", f"%{file_path}%"),
        )
        result = cur.fetchone()
        return bool(result[0]) if result else False


def _normalize_error_pattern(error_title: str) -> tuple[str, set[str]]:
    """Extract normalized pattern and keywords from error title.

    Handles variations like:
    - "PostgreSQL connection failed due to missing role"
    - "PostgreSQL connection failed due to missing user role"
    - "Database connection failed due to missing role"

    Returns:
        Tuple of (normalized_pattern, keyword_set)
    """
    title_lower = error_title.lower().strip()

    # Common substitutions to normalize variations
    substitutions = [
        # Database variations
        (r"postgresql|postgres|pg", "database"),
        (r"database connection|db connection", "database connection"),
        # Role variations
        (r"missing (user |database |db )?role", "missing role"),
        (r"role ('\w+'|`\w+`|\w+) (does not exist|not found)", "missing role"),
        # Connection variations
        (r"connection (failed|error|refused|timeout)", "connection failed"),
        (r"authentication (failed|error)", "authentication failed"),
        # UUID/JSON variations
        (r"uuid (is not json serializable|serialization)", "uuid serialization"),
        (r"json serializ(ation|able)", "json serialization"),
        # Import variations
        (r"(module|import).*not found", "import error"),
        (r"no module named", "import error"),
    ]

    normalized = title_lower
    for pattern, replacement in substitutions:
        normalized = re.sub(pattern, replacement, normalized)

    # Extract significant keywords (3+ chars, not stop words)
    stop_words = {"the", "and", "for", "due", "with", "from", "error", "fix"}
    keywords = {word for word in re.findall(r"\b\w{3,}\b", normalized) if word not in stop_words}

    return normalized, keywords


def _calculate_keyword_overlap(keywords1: set[str], keywords2: set[str]) -> float:
    """Calculate Jaccard similarity between two keyword sets."""
    if not keywords1 or not keywords2:
        return 0.0
    intersection = len(keywords1 & keywords2)
    union = len(keywords1 | keywords2)
    return intersection / union if union > 0 else 0.0


def _extract_title_keywords(title: str) -> set[str]:
    """Extract significant keywords from a task title for dedup comparison.

    Strips noise: hex IDs, pure numbers, timestamps, and stop words.
    This ensures "AutoTest: Scheduled exec 111" and "AutoTest: Scheduled exec 222"
    produce identical keyword sets and are recognized as duplicates.
    """
    title_lower = title.lower().strip()
    # Remove hex-like tokens (8+ hex chars — UUIDs, random IDs)
    title_lower = re.sub(r"\b[0-9a-f]{8,}\b", "", title_lower)
    # Remove pure numbers (timestamps, counters)
    title_lower = re.sub(r"\b\d+\b", "", title_lower)

    stop_words = {
        "the", "and", "for", "due", "with", "from", "into", "that", "this",
        "not", "but", "was", "are", "has", "had", "been",
        "task", "test", "autotest", "auto",
    }
    return {word for word in re.findall(r"\b[a-z]{3,}\b", title_lower) if word not in stop_words}


def duplicate_task_exists(
    project_id: str,
    title: str,
    exclude_task_id: str | None = None,
) -> str | None:
    """Check if a duplicate task exists based on title keyword similarity.

    Uses Jaccard similarity (>= 0.8) on extracted keywords. Strips IDs and
    timestamps so "Fix login v1" and "Fix login v2" are recognized as duplicates.

    Args:
        project_id: Project to check within
        title: Title of the new/current task
        exclude_task_id: Task ID to exclude from comparison (self)

    Returns:
        The ID of the duplicate task if found, None otherwise.
    """
    new_keywords = _extract_title_keywords(title)
    if not new_keywords:
        return None

    query = """
        SELECT id, title FROM tasks
        WHERE project_id = %s
        AND status IN ('pending', 'running', 'queue', 'paused', 'blocked', 'pr_created', 'ai_reviewing')
    """
    params: list[Any] = [project_id]
    if exclude_task_id:
        query += " AND id != %s"
        params.append(exclude_task_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)

        for row in cur.fetchall():
            existing_id, existing_title = row[0], row[1] or ""
            existing_keywords = _extract_title_keywords(existing_title)
            overlap = _calculate_keyword_overlap(new_keywords, existing_keywords)
            if overlap >= 0.8:
                return str(existing_id)

    return None


def bug_task_exists_for_error(project_id: str, error_title: str) -> bool:
    """Check if a bug task already exists for a specific error.

    Uses semantic deduplication with pattern normalization and keyword overlap
    to catch variations like "missing user role" vs "missing database role".

    Args:
        project_id: Project to check
        error_title: Error title to look for in task titles

    Returns:
        True if a pending/running bug task exists for this error
    """
    normalized_pattern, error_keywords = _normalize_error_pattern(error_title)

    with get_connection() as conn, conn.cursor() as cur:
        # First, try exact/substring match with normalized pattern
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM tasks
                WHERE project_id = %s
                AND status IN ('pending', 'running', 'paused', 'blocked', 'pr_created', 'ai_reviewing')
                AND task_type = 'bug'
                AND (
                    LOWER(title) LIKE %s
                    OR LOWER(description) LIKE %s
                )
            )
            """,
            (project_id, f"%{normalized_pattern[:50]}%", f"%{normalized_pattern[:50]}%"),
        )
        result = cur.fetchone()
        if result and result[0]:
            return True

        # Second pass: Check for keyword overlap with existing bug tasks
        # This catches semantic duplicates that substring matching misses
        cur.execute(
            """
            SELECT title, description FROM tasks
            WHERE project_id = %s
            AND status IN ('pending', 'running', 'paused', 'blocked', 'pr_created', 'ai_reviewing')
            AND task_type = 'bug'
            """,
            (project_id,),
        )

        for row in cur.fetchall():
            existing_title = row[0] or ""
            existing_desc = row[1] or ""
            combined = f"{existing_title} {existing_desc}"

            _, existing_keywords = _normalize_error_pattern(combined)
            overlap = _calculate_keyword_overlap(error_keywords, existing_keywords)

            # If 70%+ keyword overlap, consider it a duplicate
            if overlap >= 0.7:
                return True

        return False
