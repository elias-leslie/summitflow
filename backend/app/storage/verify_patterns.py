"""Verify Pattern Library - Storage layer for tracking verify_command outcomes.

This module tracks the success/failure rates of verify_commands to:
1. Provide feedback during planning (warn about low-success patterns)
2. Suggest known-working alternatives
3. Improve verification reliability over time

Pattern normalization strips:
- Task IDs (task-[a-f0-9]+)
- Absolute paths (/home/...)
- Project-specific ports (800X, 300X)
- Timestamps and session IDs
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any

from .connection import get_connection

logger = logging.getLogger(__name__)


def normalize_pattern(command: str) -> str:
    """Normalize a verify_command to find similar patterns.

    Strips:
    - Task IDs: task-[a-f0-9]+ → task-ID
    - Subtask IDs in paths: task-xxx-N.N → task-ID-N.N
    - Absolute home paths: /home/user/... → ~
    - Port numbers: localhost:800X, localhost:300X → localhost:PORT
    - UUIDs: [a-f0-9-]{36} → UUID
    - Temp file paths with random suffixes: /tmp/xxx-random → /tmp/xxx-TEMP

    Returns:
        Normalized pattern string
    """
    pattern = command

    # Normalize task IDs
    pattern = re.sub(r'task-[a-f0-9]{8}', 'task-ID', pattern)

    # Normalize absolute home paths
    pattern = re.sub(r'/home/[^/]+/', '~/', pattern)

    # Normalize port numbers (common dev ports)
    pattern = re.sub(r'localhost:80\d{2}', 'localhost:PORT', pattern)
    pattern = re.sub(r'localhost:30\d{2}', 'localhost:PORT', pattern)

    # Normalize UUIDs
    pattern = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 'UUID', pattern)

    # Normalize temp files with random suffixes
    pattern = re.sub(r'/tmp/[a-zA-Z0-9_-]+\.[a-zA-Z0-9]+', '/tmp/TEMP', pattern)

    return pattern


def _hash_pattern(normalized: str) -> str:
    """Create a hash of a normalized pattern for fast lookup."""
    return hashlib.sha256(normalized.encode()).hexdigest()


def _detect_pattern_type(command: str) -> str:
    """Detect the type of verify_command.

    Returns one of: deploy, grep, curl, test, other
    """
    cmd_lower = command.lower()

    if 'rebuild.sh' in cmd_lower or 'deploy' in cmd_lower:
        return 'deploy'
    elif 'curl' in cmd_lower:
        return 'curl'
    elif 'rg ' in cmd_lower or 'grep ' in cmd_lower:
        return 'grep'
    elif 'pytest' in cmd_lower or 'test' in cmd_lower:
        return 'test'
    else:
        return 'other'


def record_outcome(
    command: str,
    success: bool,
    duration_ms: int = 0,
    exit_code: int = 0,
) -> dict[str, Any]:
    """Record the outcome of a verify_command execution.

    Args:
        command: The actual verify_command that was executed
        success: Whether the command succeeded (output matched expected)
        duration_ms: How long the command took to run
        exit_code: The exit code of the command

    Returns:
        The updated or created pattern record
    """
    normalized = normalize_pattern(command)
    pattern_hash = _hash_pattern(normalized)
    pattern_type = _detect_pattern_type(command)
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        # Try to update existing pattern
        if success:
            cur.execute(
                """
                UPDATE verify_command_patterns
                SET success_count = success_count + 1,
                    avg_duration_ms = (avg_duration_ms * (success_count + fail_count) + %s) / (success_count + fail_count + 1),
                    last_outcome_at = %s,
                    updated_at = %s
                WHERE pattern_hash = %s
                RETURNING id, pattern_hash, normalized_pattern, command_example, pattern_type,
                          success_count, fail_count, avg_duration_ms, last_outcome_at
                """,
                (duration_ms, now, now, pattern_hash),
            )
        else:
            cur.execute(
                """
                UPDATE verify_command_patterns
                SET fail_count = fail_count + 1,
                    last_outcome_at = %s,
                    updated_at = %s
                WHERE pattern_hash = %s
                RETURNING id, pattern_hash, normalized_pattern, command_example, pattern_type,
                          success_count, fail_count, avg_duration_ms, last_outcome_at
                """,
                (now, now, pattern_hash),
            )

        row = cur.fetchone()

        if row is None:
            # Insert new pattern
            cur.execute(
                """
                INSERT INTO verify_command_patterns
                    (pattern_hash, normalized_pattern, command_example, pattern_type,
                     success_count, fail_count, avg_duration_ms, last_outcome_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, pattern_hash, normalized_pattern, command_example, pattern_type,
                          success_count, fail_count, avg_duration_ms, last_outcome_at
                """,
                (
                    pattern_hash,
                    normalized,
                    command,
                    pattern_type,
                    1 if success else 0,
                    0 if success else 1,
                    duration_ms if success else 0,
                    now,
                ),
            )
            row = cur.fetchone()

        conn.commit()

    logger.debug(
        "Recorded %s for pattern %s (hash: %s)",
        "success" if success else "failure",
        normalized[:50],
        pattern_hash[:8],
    )

    if row is None:
        raise RuntimeError("Failed to record pattern outcome")
    return _row_to_dict(row)


def get_pattern_stats(command: str) -> dict[str, Any]:
    """Get statistics for a verify_command pattern.

    Args:
        command: The verify_command to look up

    Returns:
        Dict with success_rate, total_runs, avg_duration, or defaults if not found
    """
    normalized = normalize_pattern(command)
    pattern_hash = _hash_pattern(normalized)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT success_count, fail_count, avg_duration_ms, pattern_type, last_outcome_at
            FROM verify_command_patterns
            WHERE pattern_hash = %s
            """,
            (pattern_hash,),
        )
        row = cur.fetchone()

    if row is None:
        return {
            "success_rate": None,
            "total_runs": 0,
            "avg_duration_ms": 0,
            "pattern_type": _detect_pattern_type(command),
            "found": False,
        }

    success_count, fail_count, avg_duration, pattern_type, last_outcome = row
    total = success_count + fail_count
    success_rate = (success_count / total * 100) if total > 0 else 0

    return {
        "success_rate": round(success_rate, 1),
        "total_runs": total,
        "avg_duration_ms": avg_duration,
        "pattern_type": pattern_type,
        "last_outcome_at": last_outcome.isoformat() if last_outcome else None,
        "found": True,
    }


def get_suggested_patterns(pattern_type: str, min_success_rate: float = 70.0, limit: int = 5) -> list[dict[str, Any]]:
    """Get known-good patterns of a specific type.

    Args:
        pattern_type: Type of pattern (deploy, grep, curl, test)
        min_success_rate: Minimum success rate to include (default 70%)
        limit: Maximum number of patterns to return

    Returns:
        List of high-success patterns with their stats
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT command_example, normalized_pattern, success_count, fail_count, avg_duration_ms
            FROM verify_command_patterns
            WHERE pattern_type = %s
              AND (success_count + fail_count) >= 3  -- Minimum sample size
              AND (success_count::float / NULLIF(success_count + fail_count, 0) * 100) >= %s
            ORDER BY success_count DESC
            LIMIT %s
            """,
            (pattern_type, min_success_rate, limit),
        )
        rows = cur.fetchall()

    results = []
    for row in rows:
        command, normalized, success, fail, duration = row
        total = success + fail
        results.append({
            "command_example": command,
            "normalized_pattern": normalized,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
            "total_runs": total,
            "avg_duration_ms": duration,
        })

    return results


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to a pattern dict."""
    return {
        "id": row[0],
        "pattern_hash": row[1],
        "normalized_pattern": row[2],
        "command_example": row[3],
        "pattern_type": row[4],
        "success_count": row[5],
        "fail_count": row[6],
        "avg_duration_ms": row[7],
        "last_outcome_at": row[8].isoformat() if row[8] else None,
    }
