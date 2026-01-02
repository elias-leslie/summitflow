"""Memory storage utilities - Shared helpers for memory modules.

This module provides common utilities used across memory_diary, memory_patterns,
memory_queue, and memory.py to eliminate code duplication.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

from psycopg import sql


def calculate_recency_score(
    created_at: str | datetime | None,
    half_life_days: float = 30.0,
    default: float = 0.5,
) -> float:
    """Calculate recency score using exponential decay.

    Args:
        created_at: Creation timestamp (ISO string or datetime)
        half_life_days: Decay half-life in days (default 30)
        default: Default score if created_at is None/invalid

    Returns:
        Recency score between 0 and 1.
    """
    if created_at is None:
        return default
    try:
        if isinstance(created_at, str):
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            created_dt = created_at
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        age_days = (now - created_dt).total_seconds() / 86400
        return math.exp(-age_days / half_life_days)
    except (ValueError, TypeError):
        return default


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


class _GlobalScope:
    """Sentinel for querying global patterns (project_id IS NULL)."""

    pass


GLOBAL_SCOPE: _GlobalScope = _GlobalScope()


def build_where_clause(
    filters: dict[str, Any],
    special_conditions: list[str] | None = None,
) -> tuple[sql.Composable, list[Any]]:
    """Build a WHERE clause from filters dict.

    Args:
        filters: Dict of {column_name: value} - None values are skipped.
                 Use GLOBAL_SCOPE to match NULL values (e.g., global patterns).
        special_conditions: Additional raw SQL conditions (e.g., "reflected_at IS NULL")

    Returns:
        Tuple of (sql.Composable where clause, list of params)
    """
    conditions: list[str] = []
    params: list[Any] = []

    for column, value in filters.items():
        if isinstance(value, _GlobalScope):
            # Special case: match NULL values
            conditions.append(f"{column} IS NULL")
        elif value is not None:
            conditions.append(f"{column} = %s")
            params.append(value)

    if special_conditions:
        conditions.extend(special_conditions)

    if conditions:
        where_clause: sql.Composable = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)
    else:
        where_clause = sql.SQL("TRUE")

    return where_clause, params


def rank_observation(
    obs: dict[str, Any],
    fts_score: float = 0.0,
    query_types: list[str] | None = None,
) -> float:
    """Compute multi-signal ranking score for an observation.

    Combines multiple signals with recency-weighted ranking:
    - FTS score (50%): Full-text search relevance
    - Recency (30%): Exponential decay with 30-day half-life
    - Confidence (15%): LLM extraction confidence
    - Usage (5%): Capped at 10 uses

    Args:
        obs: Observation dict with created_at, confidence, etc.
        fts_score: Normalized FTS score (0-1), from ts_rank
        query_types: Optional list of observation types (unused, kept for API compat)

    Returns:
        Combined score from 0.0 to 1.0
    """
    # Suppress unused parameter warning
    _ = query_types

    # Weight configuration
    w_fts = 0.50
    w_recency = 0.30
    w_confidence = 0.15
    w_usage = 0.05

    # 1. FTS score (already 0-1, or normalize)
    fts_norm = min(1.0, max(0.0, fts_score))

    # 2. Recency decay: exp(-age_days / 30) => 30-day half-life
    recency_score = calculate_recency_score(obs.get("created_at"))

    # 3. Confidence score (already 0-1)
    confidence = obs.get("confidence", 0.5)
    confidence_score = min(1.0, max(0.0, confidence))

    # 4. Usage frequency (capped at 10)
    usage = obs.get("usage_count", 0)
    usage_score = min(1.0, usage / 10.0)

    # Combine signals
    combined = (
        w_fts * fts_norm
        + w_recency * recency_score
        + w_confidence * confidence_score
        + w_usage * usage_score
    )

    return float(round(combined, 4))
