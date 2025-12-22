"""ObservationQueue service for fire-and-forget tool execution capture.

This service provides async enqueue of tool executions for background extraction.
Target latency: <100ms for enqueue operation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.storage import memory as memory_storage

logger = logging.getLogger(__name__)


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
    ) -> dict[str, Any]:
        """Enqueue a tool execution for async observation extraction.

        This method is designed to be fire-and-forget with <100ms latency.
        The actual extraction happens asynchronously via Celery.

        Args:
            project_id: Project ID
            session_id: Session ID (e.g., from roundtable or CLI)
            agent_type: Agent type ('claude-code', 'claude', 'gemini')
            tool_name: Name of the tool that was executed
            tool_input: Tool input parameters
            tool_output: Tool output/result
            trigger_processing: Whether to trigger Celery task after enqueue

        Returns:
            The created queue item.
        """
        start_time = time.time()

        # Insert into queue
        item = memory_storage.create_queue_item(
            project_id=project_id,
            session_id=session_id,
            agent_type=agent_type,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
        )

        # Trigger async processing
        if trigger_processing:
            try:
                from app.tasks.observation_processor import process_observation_queue

                process_observation_queue.delay()
            except ImportError:
                # Task not yet implemented - this is expected during development
                logger.debug("observation_processor task not available yet")
            except Exception as e:
                # Don't let Celery failures break the enqueue
                logger.warning(f"Failed to trigger observation processing: {e}")

        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug(
            f"Enqueued observation for {tool_name} in {elapsed_ms:.1f}ms "
            f"(session={session_id[:8]}...)"
        )

        if elapsed_ms > 100:
            logger.warning(
                f"Observation enqueue took {elapsed_ms:.1f}ms (target: <100ms)"
            )

        return item
