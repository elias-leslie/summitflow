"""Celery tasks for autonomous system maintenance and cleanup."""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.storage import tasks as task_store

logger = logging.getLogger(__name__)


@celery_app.task(name="summitflow.reset_expired_task_claims")
def reset_expired_task_claims() -> dict[str, int | str]:
    """Reset tasks with expired claim locks.

    Finds tasks where:
    - status is 'running'
    - lock_expires_at has passed
    - claimed_by is set

    Resets them to 'pending' with cleared claim fields.

    Returns:
        Dict with reset_count
    """
    try:
        count = task_store.reset_expired_claims()
        if count > 0:
            logger.info(f"Reset {count} expired task claims")
        return {"reset_count": count}
    except Exception as e:
        logger.error(f"Error resetting expired claims: {e}")
        return {"error": str(e), "reset_count": 0}
