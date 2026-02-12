"""Task claim expiration handling."""

from __future__ import annotations

import logging
from typing import TypedDict

from app.storage import tasks as task_store

logger = logging.getLogger(__name__)


class ClaimResetResult(TypedDict):
    """Result from resetting expired task claims."""

    reset_count: int
    error: str | None


def reset_expired_task_claims() -> ClaimResetResult:
    """Reset tasks with expired claim locks.

    Finds tasks where:
    - status is 'running'
    - lock_expires_at has passed
    - claimed_by is set

    Resets them to 'pending' with cleared claim fields.

    Returns:
        Dict with reset_count and optional error
    """
    try:
        count = task_store.reset_expired_claims()
        if count > 0:
            logger.info(f"Reset {count} expired task claims")
        return {"reset_count": count, "error": None}
    except Exception as e:
        logger.error(f"Error resetting expired claims: {e}")
        return {"reset_count": 0, "error": str(e)}
