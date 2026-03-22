"""Tasks storage - Deduplication helpers for task creation."""

from __future__ import annotations

import re
from typing import Any

from ..connection import get_cursor

_ACTIVE = "('pending', 'running')"
_ACTIVE_Q = "('pending', 'running')"
_STOP_WORDS_ERR = {"the", "and", "for", "due", "with", "from", "error", "fix"}
_STOP_WORDS_TITLE = {
    "the", "and", "for", "due", "with", "from", "into", "that", "this",
    "not", "but", "was", "are", "has", "had", "been", "task", "test", "autotest", "auto",
}
_ERROR_SUBS = [
    (r"postgresql|postgres|pg", "database"),
    (r"database connection|db connection", "database connection"),
    (r"missing (user |database |db )?role", "missing role"),
    (r"role ('\w+'|`\w+`|\w+) (does not exist|not found)", "missing role"),
    (r"connection (failed|error|refused|timeout)", "connection failed"),
    (r"authentication (failed|error)", "authentication failed"),
    (r"uuid (is not json serializable|serialization)", "uuid serialization"),
    (r"json serializ(ation|able)", "json serialization"),
    (r"(module|import).*not found", "import error"),
    (r"no module named", "import error"),
]


def task_exists_for_file(project_id: str, file_path: str) -> bool:
    """Check if a pending/running task targets a specific file path."""
    with get_cursor() as cur:
        cur.execute(
            f"SELECT EXISTS (SELECT 1 FROM tasks WHERE project_id = %s"
            f" AND status IN {_ACTIVE}"
            f" AND (description LIKE %s OR title LIKE %s))",
            (project_id, f"%{file_path}%", f"%{file_path}%"),
        )
        result = cur.fetchone()
        return bool(result[0]) if result else False


def list_active_tasks_for_file(
    project_id: str,
    file_path: str,
    *,
    task_type: str | None = None,
) -> list[str]:
    """Return active task IDs whose title/description target a specific file path."""
    query = (
        "SELECT id FROM tasks WHERE project_id = %s"
        f" AND status IN {_ACTIVE_Q}"
        " AND (description LIKE %s OR title LIKE %s)"
    )
    params: list[Any] = [project_id, f"%{file_path}%", f"%{file_path}%"]
    if task_type:
        query += " AND task_type = %s"
        params.append(task_type)
    query += " ORDER BY id"
    with get_cursor() as cur:
        cur.execute(query, params)
        return [str(row[0]) for row in cur.fetchall()]


def _normalize_error_pattern(error_title: str) -> tuple[str, set[str]]:
    """Return (normalized_pattern, keyword_set) for an error title."""
    s = error_title.lower().strip()
    s = re.sub(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}[.,]?\d*[Zz]?", "", s)
    s = re.sub(r"\b\d{2,}\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pattern, replacement in _ERROR_SUBS:
        s = re.sub(pattern, replacement, s)
    keywords = {w for w in re.findall(r"\b\w{3,}\b", s) if w not in _STOP_WORDS_ERR}
    return s, keywords


def _calculate_keyword_overlap(kw1: set[str], kw2: set[str]) -> float:
    """Jaccard similarity between two keyword sets."""
    if not kw1 or not kw2:
        return 0.0
    union = len(kw1 | kw2)
    return len(kw1 & kw2) / union if union > 0 else 0.0


def _extract_title_keywords(title: str) -> set[str]:
    """Strip noise and return significant keywords from a title."""
    s = title.lower().strip()
    s = re.sub(r"\b[0-9a-f]{8,}\b", "", s)
    s = re.sub(r"\b\d+\b", "", s)
    return {w for w in re.findall(r"\b[a-z]{3,}\b", s) if w not in _STOP_WORDS_TITLE}


def _desc_overlap_passes(new_desc_kw: set[str], existing_desc: str) -> bool:
    """True if description similarity >= 0.5, or if comparison is not applicable."""
    if not new_desc_kw:
        return True
    existing_kw = _extract_title_keywords(existing_desc)
    return not existing_kw or _calculate_keyword_overlap(new_desc_kw, existing_kw) >= 0.5


def _find_duplicate_in_rows(
    rows: list[Any], new_kw: set[str], new_desc_kw: set[str]
) -> str | None:
    """Return the first row's ID whose title/description overlaps sufficiently."""
    for row in rows:
        existing_kw = _extract_title_keywords(row[1] or "")
        if _calculate_keyword_overlap(new_kw, existing_kw) < 0.9:
            continue
        if _desc_overlap_passes(new_desc_kw, row[2] or ""):
            return str(row[0])
    return None


def duplicate_task_exists(
    project_id: str,
    title: str,
    exclude_task_id: str | None = None,
    description: str | None = None,
) -> str | None:
    """Return ID of a duplicate task (Jaccard >= 0.9 on title keywords), or None."""
    new_kw = _extract_title_keywords(title)
    if len(new_kw) < 3:
        return None
    new_desc_kw = _extract_title_keywords(description) if description else set()
    query = "SELECT id, title, description FROM tasks WHERE project_id = %s AND status IN " + _ACTIVE_Q
    params: list[Any] = [project_id]
    if exclude_task_id:
        query += " AND id != %s"
        params.append(exclude_task_id)
    with get_cursor() as cur:
        cur.execute(query, params)
        return _find_duplicate_in_rows(cur.fetchall(), new_kw, new_desc_kw)


def _bug_exact_match(cur: Any, project_id: str, pattern_prefix: str) -> bool:
    """True if any bug task matches the normalized pattern prefix via LIKE."""
    cur.execute(
        f"SELECT EXISTS (SELECT 1 FROM tasks WHERE project_id = %s"
        f" AND status IN {_ACTIVE} AND task_type = 'bug'"
        f" AND (LOWER(title) LIKE %s OR LOWER(description) LIKE %s))",
        (project_id, f"%{pattern_prefix}%", f"%{pattern_prefix}%"),
    )
    result = cur.fetchone()
    return bool(result and result[0])


def _bug_keyword_match(cur: Any, project_id: str, error_kw: set[str]) -> bool:
    """True if any existing bug task has >= 0.7 keyword overlap."""
    cur.execute(
        f"SELECT title, description FROM tasks WHERE project_id = %s"
        f" AND status IN {_ACTIVE} AND task_type = 'bug'",
        (project_id,),
    )
    for row in cur.fetchall():
        combined = f"{row[0] or ''} {row[1] or ''}"
        _, existing_kw = _normalize_error_pattern(combined)
        if _calculate_keyword_overlap(error_kw, existing_kw) >= 0.7:
            return True
    return False


def bug_task_exists_for_error(project_id: str, error_title: str) -> bool:
    """True if a bug task already exists for this error (semantic dedup)."""
    normalized, error_kw = _normalize_error_pattern(error_title)
    with get_cursor() as cur:
        if _bug_exact_match(cur, project_id, normalized[:50]):
            return True
        return _bug_keyword_match(cur, project_id, error_kw)
