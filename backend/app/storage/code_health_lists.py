"""Code health lists storage layer - Allow/block list CRUD operations.

This module provides data access for code health allow/block lists, used to
filter false positives and track known issues during code quality scans.
"""

from __future__ import annotations

from typing import Any

from .connection import get_connection


def create_list_entry(
    project_id: str,
    list_type: str,
    category: str,
    pattern: str,
    file_glob: str | None = None,
    reason: str | None = None,
    confidence: float = 1.0,
    source: str = "manual",
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create a new code health list entry.

    Args:
        project_id: Project ID
        list_type: 'allow' (false positive) or 'block' (known issue)
        category: Pattern category (e.g., 'compat_comments', 'magic_strings')
        pattern: The pattern/value to match
        file_glob: Optional file glob to scope the rule
        reason: Optional explanation for the rule
        confidence: Confidence score (0.0-1.0), default 1.0
        source: How the entry was created ('manual', 'agent', 'memory')
        created_by: Who/what created this entry

    Returns:
        The created list entry dict.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO code_health_lists
                (project_id, list_type, category, pattern, file_glob,
                 reason, confidence, source, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, list_type, category, pattern, COALESCE(file_glob, ''))
            DO UPDATE SET
                reason = EXCLUDED.reason,
                confidence = EXCLUDED.confidence,
                source = EXCLUDED.source,
                created_by = EXCLUDED.created_by
            RETURNING id, project_id, list_type, category, pattern, file_glob,
                      reason, confidence, source, created_by, created_at
            """,
            (
                project_id,
                list_type,
                category,
                pattern,
                file_glob,
                reason,
                confidence,
                source,
                created_by,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else {}


def get_list_entries(
    project_id: str,
    list_type: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Get code health list entries for a project.

    Args:
        project_id: Project ID
        list_type: Optional filter by 'allow' or 'block'
        category: Optional filter by category

    Returns:
        List of entry dicts.
    """
    with get_connection() as conn, conn.cursor() as cur:
        query = """
            SELECT id, project_id, list_type, category, pattern, file_glob,
                   reason, confidence, source, created_by, created_at
            FROM code_health_lists
            WHERE project_id = %s
        """
        params: list[Any] = [project_id]

        if list_type:
            query += " AND list_type = %s"
            params.append(list_type)
        if category:
            query += " AND category = %s"
            params.append(category)

        query += " ORDER BY created_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_allow_list(project_id: str, category: str | None = None) -> list[dict[str, Any]]:
    """Get allow list entries (false positives) for a project.

    Args:
        project_id: Project ID
        category: Optional filter by category

    Returns:
        List of allow list entry dicts.
    """
    return get_list_entries(project_id, list_type="allow", category=category)


def get_block_list(project_id: str, category: str | None = None) -> list[dict[str, Any]]:
    """Get block list entries (known issues) for a project.

    Args:
        project_id: Project ID
        category: Optional filter by category

    Returns:
        List of block list entry dicts.
    """
    return get_list_entries(project_id, list_type="block", category=category)


def delete_list_entry(entry_id: int) -> bool:
    """Delete a code health list entry by ID.

    Args:
        entry_id: The entry ID to delete

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM code_health_lists WHERE id = %s RETURNING id",
            (entry_id,),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None


def is_pattern_allowed(
    project_id: str,
    category: str,
    pattern: str,
    file_path: str | None = None,
) -> bool:
    """Check if a pattern is in the allow list (false positive).

    Args:
        project_id: Project ID
        category: Pattern category
        pattern: The pattern/value to check
        file_path: Optional file path for glob matching

    Returns:
        True if the pattern is allowed (should be ignored).
    """
    import fnmatch

    entries = get_allow_list(project_id, category=category)
    for entry in entries:
        if entry["pattern"] == pattern:
            # Check file glob if present
            if entry["file_glob"] and file_path:
                if fnmatch.fnmatch(file_path, entry["file_glob"]):
                    return True
            elif not entry["file_glob"]:
                # No file glob = applies everywhere
                return True
    return False


def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if not row:
        return {}
    return {
        "id": row[0],
        "project_id": row[1],
        "list_type": row[2],
        "category": row[3],
        "pattern": row[4],
        "file_glob": row[5],
        "reason": row[6],
        "confidence": row[7],
        "source": row[8],
        "created_by": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
    }
