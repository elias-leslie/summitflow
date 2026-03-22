#!/usr/bin/env python3
"""Backfill task_outcome in context_access_log from session_diary.

This script is used to populate task_outcome for context_access_log entries
that were created before the automatic backfill mechanism was added.

Run from backend directory:
    .venv/bin/python scripts/backfill_context_access_outcomes.py

The script will:
1. Find all session_diary entries with outcomes
2. Match them to context_access_log entries by session_id
3. Update the task_outcome field where it's currently NULL
4. Report statistics

"""

import logging
import sys
from pathlib import Path
from typing import Any

# Auto-detect and re-exec into the backend venv if needed
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import lib.ensure_backend_venv  # noqa: F401

from app.storage.connection import get_connection, get_cursor

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _update_session_outcome(cur: Any, session_id: str, outcome: str) -> int:
    """Update context_access_log entries for one session.

    Returns the number of rows updated.
    """
    cur.execute(
        """
        UPDATE context_access_log
        SET task_outcome = %s
        WHERE session_id = %s
          AND task_outcome IS NULL
        """,
        (outcome, session_id),
    )
    return cur.rowcount or 0


def _process_session(cur: Any, session_id: str, outcome: str, stats: dict[str, int]) -> None:
    """Process a single diary entry and update stats in-place."""
    try:
        updated = _update_session_outcome(cur, session_id, outcome)
        if updated > 0:
            stats["entries_updated"] += updated
            logger.debug("  Session %s...: %d entries updated", session_id[:8], updated)
        stats["sessions_processed"] += 1
    except Exception as e:
        stats["errors"] += 1
        logger.error("  Error processing session %s: %s", session_id, e)


def backfill_outcomes() -> dict[str, int]:
    """Backfill task_outcome from session_diary to context_access_log.

    Returns:
        Dict with statistics: total_sessions, entries_updated, errors
    """
    stats = {"sessions_processed": 0, "entries_updated": 0, "errors": 0}

    with get_connection() as conn, conn.cursor() as cur:
        # Find all diary entries with outcomes
        cur.execute(
            """
            SELECT DISTINCT session_id, outcome
            FROM session_diary
            WHERE outcome IS NOT NULL
            ORDER BY session_id
            """
        )
        diary_entries = cur.fetchall()

        logger.info("Found %d session diary entries with outcomes", len(diary_entries))

        # For each diary entry, update context_access_log
        for session_id, outcome in diary_entries:
            _process_session(cur, session_id, outcome, stats)

        conn.commit()

    return stats


def _get_outcome_counts(cur: Any) -> tuple[int, int]:
    """Return (null_count, filled_count) from context_access_log."""
    cur.execute("SELECT COUNT(*) FROM context_access_log WHERE task_outcome IS NULL")
    null_row = cur.fetchone()
    assert null_row is not None
    null_count = null_row[0]

    cur.execute("SELECT COUNT(*) FROM context_access_log WHERE task_outcome IS NOT NULL")
    filled_row = cur.fetchone()
    assert filled_row is not None
    filled_count = filled_row[0]

    return null_count, filled_count


def main() -> int:
    """Run the backfill and report statistics."""
    logger.info("Starting context_access_log outcome backfill...")

    # Check current state
    with get_cursor() as cur:
        null_count, filled_count = _get_outcome_counts(cur)

    logger.info("Current state: %d with outcomes, %d without", filled_count, null_count)

    if null_count == 0:
        logger.info("No entries need backfilling. Exiting.")
        return 0

    # Run backfill
    stats = backfill_outcomes()

    logger.info("Backfill complete!")
    logger.info("  Sessions processed: %d", stats["sessions_processed"])
    logger.info("  Entries updated: %d", stats["entries_updated"])
    logger.info("  Errors: %d", stats["errors"])

    # Verify final state
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM context_access_log WHERE task_outcome IS NULL")
        remaining_row = cur.fetchone()
        assert remaining_row is not None
        remaining = remaining_row[0]
        logger.info("  Remaining NULL entries: %d", remaining)

    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
