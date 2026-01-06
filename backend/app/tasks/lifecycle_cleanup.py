"""Celery tasks for memory lifecycle cleanup.

Tasks:
- cleanup_failed_queue_items: Archive failed queue items older than 14 days
- cleanup_old_checkpoints: Delete checkpoints older than 30 days
- reset_stuck_queue_items: Reset items stuck in 'processing' for > 1 hour
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..storage import memory as memory_storage

logger = get_logger(__name__)


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.cleanup_failed_queue_items",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def cleanup_failed_queue_items(
    self: Any,
    max_age_days: int = 14,
) -> dict[str, Any]:
    """Archive failed queue items older than max_age_days.

    Runs daily to prevent accumulation of failed items.

    Args:
        max_age_days: Delete failed items older than this (default: 14 days)

    Returns:
        Summary dict with deleted count.
    """
    logger.info(f"cleanup_failed_queue_items: starting, max_age_days={max_age_days}")

    deleted = memory_storage.archive_failed_queue_items(max_age_days=max_age_days)

    summary = {
        "task": "cleanup_failed_queue_items",
        "max_age_days": max_age_days,
        "deleted_count": deleted,
    }

    logger.info(f"cleanup_failed_queue_items: completed, deleted={deleted}")
    return summary


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.cleanup_old_checkpoints",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def cleanup_old_checkpoints(
    self: Any,
    max_age_days: int = 30,
) -> dict[str, Any]:
    """Delete checkpoints older than max_age_days.

    Runs weekly to prevent checkpoint accumulation.

    Args:
        max_age_days: Delete checkpoints older than this (default: 30 days)

    Returns:
        Summary dict with deleted count.
    """
    logger.info(f"cleanup_old_checkpoints: starting, max_age_days={max_age_days}")

    deleted = memory_storage.cleanup_old_checkpoints(max_age_days=max_age_days)

    summary = {
        "task": "cleanup_old_checkpoints",
        "max_age_days": max_age_days,
        "deleted_count": deleted,
    }

    logger.info(f"cleanup_old_checkpoints: completed, deleted={deleted}")
    return summary


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.reset_stuck_queue_items",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def reset_stuck_queue_items(
    self: Any,
    threshold_minutes: int = 60,
) -> dict[str, Any]:
    """Reset queue items stuck in 'processing' status.

    Runs hourly to recover stuck items so they can be reprocessed.

    Args:
        threshold_minutes: Reset items stuck longer than this (default: 60 min)

    Returns:
        Summary dict with reset count.
    """
    logger.info(f"reset_stuck_queue_items: starting, threshold_minutes={threshold_minutes}")

    reset_count = memory_storage.reset_stuck_queue_items(threshold_minutes=threshold_minutes)

    summary = {
        "task": "reset_stuck_queue_items",
        "threshold_minutes": threshold_minutes,
        "reset_count": reset_count,
    }

    logger.info(f"reset_stuck_queue_items: completed, reset_count={reset_count}")
    return summary
