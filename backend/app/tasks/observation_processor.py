"""Celery tasks for processing observation queue.

Tasks:
- process_observation_queue: Process pending observation queue items
"""

from __future__ import annotations

import asyncio
from typing import Any

import redis
from celery import shared_task

from ..logging_config import get_logger
from ..services.memory import ContextBuilder, ObservationExtractor
from ..storage import memory as memory_storage

logger = get_logger(__name__)

# Max items to process in one task execution
BATCH_SIZE = 50

# Max retries before marking item as permanently failed
MAX_RETRIES = 3

# Redis connection for pub/sub
REDIS_URL = "redis://localhost:6379/1"


def _run_async(coro):
    """Run async function in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    name="summitflow.process_observation_queue",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def process_observation_queue(self, limit: int = BATCH_SIZE) -> dict[str, Any]:
    """Process pending items in observation queue.

    Fetches pending items, runs extraction, and saves observations.
    Publishes Redis events for SSE streaming.

    Args:
        limit: Max items to process in this run

    Returns:
        Summary dict with processed/failed counts
    """
    logger.info("observation_queue_processing_started", limit=limit)

    processed = 0
    failed = 0
    skipped = 0

    try:
        # Get pending items
        pending_items = memory_storage.get_pending_queue_items(limit=limit)

        if not pending_items:
            logger.debug("observation_queue_empty")
            return {"processed": 0, "failed": 0, "skipped": 0}

        logger.info("observation_queue_items_found", count=len(pending_items))

        # Mark all items as processing before LLM call
        for item in pending_items:
            memory_storage.update_queue_item_status(item["id"], "processing")

        # Create extractor and run batch extraction (single LLM call)
        extractor = ObservationExtractor()
        observations = _run_async(extractor.extract_batch(pending_items))

        # Process results - each observation corresponds to the item at same index
        for idx, (item, observation) in enumerate(zip(pending_items, observations)):
            try:
                if observation.skipped:
                    # Mark as processed but don't create observation
                    memory_storage.update_queue_item_status(
                        item["id"],
                        "processed",
                        error_message=f"Skipped: {observation.skip_reason}",
                    )
                    skipped += 1
                    logger.debug(
                        "observation_skipped",
                        item_id=item["id"],
                        reason=observation.skip_reason,
                    )
                    continue

                # Save observation
                obs = memory_storage.create_observation(
                    project_id=item["project_id"],
                    session_id=item["session_id"],
                    agent_type=item["agent_type"],
                    observation_type=observation.observation_type,
                    title=observation.title,
                    concepts=observation.concepts,
                    subtitle=observation.subtitle,
                    narrative=observation.narrative,
                    facts=observation.facts,
                    files_read=observation.files_read,
                    files_modified=observation.files_modified,
                    tool_name=item["tool_name"],
                    tool_input=item["tool_input"],
                    discovery_tokens=observation.discovery_tokens,
                    extracted_by=observation.extracted_by,
                )

                # Mark queue item as processed
                memory_storage.update_queue_item_status(item["id"], "processed")

                # Publish event for SSE
                _publish_observation_event(item["project_id"], obs)

                # Invalidate context cache (new observation changes context)
                ContextBuilder.invalidate_cache(item["project_id"])

                processed += 1
                logger.info(
                    "observation_extracted",
                    item_id=item["id"],
                    observation_id=obs["id"],
                    observation_type=observation.observation_type,
                    discovery_tokens=observation.discovery_tokens,
                )

            except Exception as e:
                # Check retry count
                if item.get("retry_count", 0) >= MAX_RETRIES:
                    memory_storage.update_queue_item_status(
                        item["id"], "failed", error_message=str(e)
                    )
                    failed += 1
                    logger.error(
                        "observation_extraction_failed_permanently",
                        item_id=item["id"],
                        error=str(e),
                    )
                else:
                    # Leave as pending for retry
                    memory_storage.update_queue_item_status(
                        item["id"], "pending", error_message=str(e)
                    )
                    logger.warning(
                        "observation_extraction_failed_retrying",
                        item_id=item["id"],
                        retry_count=item.get("retry_count", 0) + 1,
                        error=str(e),
                    )

        result = {"processed": processed, "failed": failed, "skipped": skipped}
        logger.info("observation_queue_processing_completed", **result)

        # Schedule diary aggregation for each unique session (with 5 min delay)
        if processed > 0:
            _schedule_diary_aggregation(pending_items)

        return result

    except Exception as e:
        logger.error("observation_queue_processing_error", error=str(e))
        raise


# Track pending diary aggregations to avoid duplicates
_pending_diary_sessions: set[tuple[str, str]] = set()
DIARY_AGGREGATION_DELAY = 300  # 5 minutes


def _schedule_diary_aggregation(items: list[dict[str, Any]]) -> None:
    """Schedule diary aggregation for sessions in the processed batch.

    Uses apply_async with countdown to delay execution, giving time for
    more observations from the same session to be processed.
    """
    from .diary_aggregator import aggregate_session_diary

    # Get unique (project_id, session_id) pairs
    sessions: set[tuple[str, str]] = set()
    for item in items:
        sessions.add((item["project_id"], item["session_id"]))

    for project_id, session_id in sessions:
        key = (project_id, session_id)
        if key in _pending_diary_sessions:
            logger.debug(
                f"diary_aggregation_already_scheduled: session={session_id[:16]}..."
            )
            continue

        # Schedule with delay
        try:
            aggregate_session_diary.apply_async(
                args=[project_id, session_id],
                countdown=DIARY_AGGREGATION_DELAY,
            )
            _pending_diary_sessions.add(key)
            logger.info(
                f"diary_aggregation_scheduled: session={session_id[:16]}..., "
                f"delay={DIARY_AGGREGATION_DELAY}s"
            )
        except Exception as e:
            logger.warning(f"Failed to schedule diary aggregation: {e}")


def _publish_observation_event(project_id: str, observation: dict[str, Any]) -> None:
    """Publish observation event to Redis for SSE streaming."""
    try:
        import json

        r = redis.from_url(REDIS_URL)
        channel = f"observations:{project_id}"
        message = json.dumps(
            {
                "event": "observation_created",
                "data": observation,
            }
        )
        r.publish(channel, message)
        logger.debug("observation_event_published", channel=channel)
    except Exception as e:
        # Don't fail the task for pub/sub errors
        logger.warning("observation_event_publish_failed", error=str(e))
