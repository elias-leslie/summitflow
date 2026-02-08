"""Tasks storage - Deduplication helpers for task creation.

This module provides semantic matching to prevent duplicate tasks.
"""

from __future__ import annotations

import re

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
