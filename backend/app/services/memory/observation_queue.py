"""ObservationQueue service for fire-and-forget tool execution capture.

This service provides async enqueue of tool executions for background extraction.
Target latency: <100ms for enqueue operation.

Includes Redis-based debouncing to prevent Celery task storms.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import redis

from app.storage import memory as memory_storage

logger = logging.getLogger(__name__)

# Redis for debouncing
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DEBOUNCE_SECONDS = 5  # Only trigger Celery task once per 5 seconds per project


def _get_redis() -> redis.Redis | None:
    """Get Redis connection for debouncing.

    Returns None if Redis is unavailable (graceful degradation).
    """
    try:
        r: redis.Redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1)
        r.ping()  # Verify connection
        return r
    except redis.RedisError as e:
        logger.warning(f"Redis unavailable for debouncing: {e}")
        return None


class ObservationQueue:
    """Fire-and-forget queue for tool execution capture.

    Usage:
        queue = ObservationQueue()
        await queue.enqueue(
            project_id="summitflow",
            session_id="session-123",
            agent_type="claude-code",
            tool_name="Read",
            tool_input={"file": "main.py"},
            tool_output="file contents..."
        )
    """

    async def enqueue(
        self,
        project_id: str,
        session_id: str,
        agent_type: str,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
        tool_output: str | None = None,
        trigger_processing: bool = True,
    ) -> dict[str, Any] | None:
        """Enqueue a tool execution for async observation extraction.

        This method is designed to be fire-and-forget with <100ms latency.
        The actual extraction happens asynchronously via Celery.

        Args:
            project_id: Project ID
            session_id: Session ID (e.g., from CLI)
            agent_type: Agent type ('claude-code', 'claude', 'gemini')
            tool_name: Name of the tool that was executed
            tool_input: Tool input parameters
            tool_output: Tool output/result
            trigger_processing: Whether to trigger Celery task after enqueue

        Returns:
            The created queue item, or None if memory is disabled.
        """
        start_time = time.time()

        # Insert into queue (returns None if memory disabled for project)
        item = memory_storage.create_queue_item(
            project_id=project_id,
            session_id=session_id,
            agent_type=agent_type,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
        )

        # Memory disabled - skip processing
        if item is None:
            logger.debug(f"Memory disabled for {project_id}, skipping enqueue")
            return None

        # Trigger async processing with debouncing
        if trigger_processing:
            should_trigger = self._acquire_debounce_lock(project_id)
            if should_trigger:
                try:
                    from app.tasks.observation_processor import process_observation_queue

                    process_observation_queue.delay()
                    logger.debug(f"Triggered observation processing for {project_id}")
                except ImportError:
                    # Task not yet implemented - this is expected during development
                    logger.debug("observation_processor task not available yet")
                except Exception as e:
                    # Don't let Celery failures break the enqueue
                    logger.warning(f"Failed to trigger observation processing: {e}")
            else:
                logger.debug(
                    f"Debounced Celery trigger for {project_id} (lock held, task already scheduled)"
                )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug(
            f"Enqueued observation for {tool_name} in {elapsed_ms:.1f}ms "
            f"(session={session_id[:8]}...)"
        )

        if elapsed_ms > 100:
            logger.warning(f"Observation enqueue took {elapsed_ms:.1f}ms (target: <100ms)")

        return item

    def _acquire_debounce_lock(self, project_id: str) -> bool:
        """Try to acquire debounce lock for a project.

        Uses Redis SET NX EX to atomically check-and-set a lock.
        The lock auto-expires after DEBOUNCE_SECONDS.

        Returns:
            True if lock acquired (should trigger Celery), False if debounced.
        """
        r = _get_redis()
        if r is None:
            # Redis unavailable - don't debounce, trigger every time
            logger.debug("Redis unavailable, skipping debounce (will trigger)")
            return True

        lock_key = f"obs_processing_lock:{project_id}"
        try:
            # SET NX EX: only set if not exists, with expiry
            acquired = r.set(lock_key, "1", nx=True, ex=DEBOUNCE_SECONDS)
            return bool(acquired)
        except redis.RedisError as e:
            logger.warning(f"Redis error during debounce lock: {e}")
            return True  # On error, trigger processing
