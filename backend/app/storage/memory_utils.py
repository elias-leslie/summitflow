"""Memory storage utilities - Shared helpers for memory modules.

This module provides common utilities used across memory_diary, memory_patterns,
memory_queue, and memory.py to eliminate code duplication.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg import sql


def json_or_default(obj: Any, default: str | None = None) -> str | None:
    """Serialize object to JSON or return default if falsy.

    Args:
        obj: Object to serialize (list, dict, etc.)
        default: Value to return if obj is falsy (None, empty list, empty dict)

    Returns:
        JSON string or default value.
    """
    if obj is None or obj == {} or obj == []:
        return default
    return json.dumps(obj)


def normalize_timestamp(value: datetime | None) -> str | None:
    """Convert datetime to ISO format string or None.

    Args:
        value: Datetime object or None

    Returns:
        ISO format string or None.
    """
    return value.isoformat() if value else None


def build_where_clause(
    filters: dict[str, Any],
    special_conditions: list[str] | None = None,
) -> tuple[sql.SQL | sql.Composed, list[Any]]:
    """Build a WHERE clause from filters dict.

    Args:
        filters: Dict of {column_name: value} - None values are skipped
        special_conditions: Additional raw SQL conditions (e.g., "reflected_at IS NULL")

    Returns:
        Tuple of (sql.SQL where clause, list of params)
    """
    conditions: list[str] = []
    params: list[Any] = []

    for column, value in filters.items():
        if value is not None:
            conditions.append(f"{column} = %s")
            params.append(value)

    if special_conditions:
        conditions.extend(special_conditions)

    if conditions:
        where_clause = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)  # type: ignore[arg-type]
    else:
        where_clause = sql.SQL("TRUE")

    return where_clause, params
