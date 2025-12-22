"""Celery tasks for reflection processing.

Tasks:
- process_reflection: Run reflection analysis on diary entries
- check_reflection_trigger: Check if reflection should be triggered

Event-driven triggers:
- After N diary entries (configurable, default 3)
- After feature completion (manual trigger)
"""

from __future__ import annotations

from typing import Any

import redis
from celery import shared_task

from ..logging_config import get_logger
from ..services.memory import ReflectionService
from ..storage import memory as memory_storage

logger = get_logger(__name__)

# Default trigger threshold
DEFAULT_DIARY_THRESHOLD = 3

# Auto-apply threshold (patterns with confidence >= this are auto-applied)
DEFAULT_AUTO_APPLY_THRESHOLD = 0.9

# Redis connection for notifications
REDIS_URL = "redis://localhost:6379/1"


@shared_task(
    name="summitflow.process_reflection",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def process_reflection(
    self,
    project_id: str,
    project_path: str | None = None,
    auto_apply: bool = True,
    auto_apply_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
    limit: int = 10,
) -> dict[str, Any]:
    """Run reflection analysis on diary entries.

    Analyzes unreflected diary entries and generates pattern suggestions.
    High-confidence patterns can be auto-applied.

    Args:
        project_id: Project to run reflection on
        project_path: Path to project root (for auto-applying patterns)
        auto_apply: Whether to auto-apply high-confidence patterns
        auto_apply_threshold: Min confidence for auto-apply
        limit: Max diary entries to analyze

    Returns:
        Summary dict with suggestions/patterns created
    """
    logger.info(
        "reflection_processing_started",
        project_id=project_id,
        auto_apply=auto_apply,
        threshold=auto_apply_threshold,
    )

    try:
        # Create reflection service
        reflection_service = ReflectionService(
            project_id=project_id,
            project_path=project_path,
            auto_apply_threshold=auto_apply_threshold,
        )

        # Run reflection
        result = reflection_service.analyze_diary(
            limit=limit,
            auto_apply=auto_apply,
        )

        # Publish notification if patterns were created
        if result.patterns_created:
            _publish_reflection_event(project_id, {
                "patterns_created": len(result.patterns_created),
                "patterns_auto_applied": len(result.patterns_auto_applied),
                "diary_entries_processed": len(result.diary_ids_processed),
            })

        summary = {
            "diary_entries_processed": len(result.diary_ids_processed),
            "suggestions": len(result.suggestions),
            "patterns_created": len(result.patterns_created),
            "patterns_auto_applied": len(result.patterns_auto_applied),
            "tokens_used": result.tokens_used,
            "errors": result.errors,
        }

        logger.info("reflection_processing_completed", **summary)
        return summary

    except Exception as e:
        logger.error("reflection_processing_error", error=str(e))
        raise


@shared_task(
    name="summitflow.check_reflection_trigger",
    bind=True,
)
def check_reflection_trigger(
    self,
    project_id: str,
    project_path: str | None = None,
    threshold: int = DEFAULT_DIARY_THRESHOLD,
    auto_apply: bool = True,
) -> dict[str, Any]:
    """Check if reflection should be triggered and run if needed.

    This task can be called after diary entries are created to check
    if the threshold has been reached.

    Args:
        project_id: Project to check
        project_path: Path to project root (for auto-applying patterns)
        threshold: Number of unreflected entries to trigger
        auto_apply: Whether to auto-apply high-confidence patterns

    Returns:
        Summary dict indicating if reflection was triggered
    """
    try:
        # Check unreflected count
        count = memory_storage.get_unreflected_diary_count(project_id)

        logger.debug(
            "reflection_trigger_check",
            project_id=project_id,
            unreflected_count=count,
            threshold=threshold,
        )

        if count >= threshold:
            logger.info(
                "reflection_trigger_activated",
                project_id=project_id,
                unreflected_count=count,
                threshold=threshold,
            )

            # Trigger reflection
            result = process_reflection.delay(
                project_id=project_id,
                project_path=project_path,
                auto_apply=auto_apply,
            )

            return {
                "triggered": True,
                "unreflected_count": count,
                "task_id": result.id,
            }

        return {
            "triggered": False,
            "unreflected_count": count,
            "threshold": threshold,
        }

    except Exception as e:
        logger.error("reflection_trigger_check_error", error=str(e))
        return {
            "triggered": False,
            "error": str(e),
        }


@shared_task(
    name="summitflow.trigger_feature_reflection",
    bind=True,
)
def trigger_feature_reflection(
    self,
    project_id: str,
    feature_id: str,
    project_path: str | None = None,
    auto_apply: bool = True,
) -> dict[str, Any]:
    """Trigger reflection after feature completion.

    Called when a feature is marked complete. Analyzes all diary entries
    since the feature started.

    Args:
        project_id: Project ID
        feature_id: Completed feature ID
        project_path: Path to project root
        auto_apply: Whether to auto-apply high-confidence patterns

    Returns:
        Summary dict with reflection results
    """
    logger.info(
        "feature_reflection_triggered",
        project_id=project_id,
        feature_id=feature_id,
    )

    try:
        # Trigger reflection with higher limit for features
        result = process_reflection.delay(
            project_id=project_id,
            project_path=project_path,
            auto_apply=auto_apply,
            limit=20,  # More entries for feature reflection
        )

        return {
            "triggered": True,
            "feature_id": feature_id,
            "task_id": result.id,
        }

    except Exception as e:
        logger.error(
            "feature_reflection_trigger_error",
            feature_id=feature_id,
            error=str(e),
        )
        return {
            "triggered": False,
            "error": str(e),
        }


def _publish_reflection_event(project_id: str, data: dict[str, Any]) -> None:
    """Publish reflection event to Redis for notifications."""
    try:
        import json

        r = redis.from_url(REDIS_URL)
        channel = f"reflection:{project_id}"
        message = json.dumps({
            "event": "reflection_completed",
            "data": data,
        })
        r.publish(channel, message)
        logger.debug("reflection_event_published", channel=channel)
    except Exception as e:
        # Don't fail for pub/sub errors
        logger.warning("reflection_event_publish_failed", error=str(e))
