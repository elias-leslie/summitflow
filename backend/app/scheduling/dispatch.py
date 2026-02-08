"""Event-driven task dispatch via Redis pub/sub.

Replaces 30-minute polling with immediate task pickup.
Uses Redis pub/sub for low-latency event delivery.
Uses Redis-based distributed locking to prevent race conditions.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import redis

from app.config import REDIS_URL
from app.logging_config import get_logger

from .types import OnceSchedule, TaskSchedule, parse_schedule

logger = get_logger(__name__)

# Lock settings for distributed locking
DISPATCH_LOCK_PREFIX = "summitflow:dispatch_lock:"
DISPATCH_LOCK_TTL = 3600  # Lock TTL in seconds — matches execution time_limit to prevent re-dispatch

CHANNEL_TASK_DISPATCH = "summitflow:task_dispatch"
CHANNEL_SCHEDULED = "summitflow:scheduled_tasks"


@dataclass
class DispatchEvent:
    """Event published when a task is ready for pickup.

    Attributes:
        task_id: Task to dispatch
        project_id: Project the task belongs to
        schedule: Optional schedule (None = immediate)
        queued_at: When the event was created
    """

    task_id: str
    project_id: str
    schedule: TaskSchedule | None = None
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for Redis."""
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "schedule": self.schedule.to_dict() if self.schedule else None,
            "queued_at": self.queued_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DispatchEvent:
        """Deserialize from Redis message."""
        schedule = None
        schedule_data = data.get("schedule")
        if schedule_data and isinstance(schedule_data, dict):
            schedule = parse_schedule(schedule_data)
        return cls(
            task_id=str(data["task_id"]),
            project_id=str(data["project_id"]),
            schedule=schedule,
            queued_at=datetime.fromisoformat(str(data["queued_at"])),
        )


class EventDispatcher:
    """Redis pub/sub dispatcher for task events.

    Publisher side:
        dispatcher = get_dispatcher()
        dispatcher.publish_task_ready("task-123", "summitflow")

    Subscriber side (in Celery worker):
        dispatcher.subscribe(callback_fn)
    """

    def __init__(self, redis_url: str = REDIS_URL) -> None:
        self._redis_url = f"{redis_url}/1"
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._subscriber_thread: threading.Thread | None = None
        self._running = False

    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url)  # type: ignore[no-untyped-call]
        return self._redis

    def publish_task_ready(
        self,
        task_id: str,
        project_id: str,
        schedule: TaskSchedule | None = None,
    ) -> bool:
        """Publish a task dispatch event.

        Uses distributed locking to prevent race conditions when multiple
        processes try to dispatch the same task simultaneously.

        Args:
            task_id: Task to dispatch
            project_id: Project ID
            schedule: Optional schedule (None = immediate dispatch)

        Returns:
            True if published successfully
        """
        # Acquire lock to prevent duplicate dispatch
        if not self.acquire_dispatch_lock(task_id):
            logger.info(
                "Task already being dispatched, skipping",
                task_id=task_id,
                project_id=project_id,
            )
            return False

        event = DispatchEvent(
            task_id=task_id,
            project_id=project_id,
            schedule=schedule,
        )

        try:
            if schedule is None:
                channel = CHANNEL_TASK_DISPATCH
                logger.info(
                    "Publishing immediate dispatch",
                    task_id=task_id,
                    project_id=project_id,
                )
            else:
                channel = CHANNEL_SCHEDULED
                logger.info(
                    "Publishing scheduled dispatch",
                    task_id=task_id,
                    project_id=project_id,
                    schedule=schedule.to_dict(),
                )

            message = json.dumps(event.to_dict())
            self.redis.publish(channel, message)

            if isinstance(schedule, OnceSchedule):
                self._store_scheduled_task(event)

            return True

        except redis.RedisError as e:
            logger.warning("Failed to publish dispatch event", error=str(e))
            # Release lock on failure so task can be retried
            self.release_dispatch_lock(task_id)
            return False

    def _store_scheduled_task(self, event: DispatchEvent) -> None:
        """Store scheduled task in Redis sorted set for delayed execution."""
        if event.schedule is None:
            return

        next_run = event.schedule.next_run()
        if next_run is None:
            return

        key = "summitflow:scheduled_tasks"
        score = next_run.timestamp()
        value = json.dumps(event.to_dict())

        self.redis.zadd(key, {value: score})
        logger.debug(
            "Stored scheduled task",
            task_id=event.task_id,
            next_run=next_run.isoformat(),
        )

    def acquire_dispatch_lock(self, task_id: str) -> bool:
        """Acquire a distributed lock for task dispatch.

        Uses Redis SET NX (set if not exists) with TTL for atomic locking.
        Prevents race conditions when multiple workers try to dispatch the same task.

        Args:
            task_id: Task ID to lock

        Returns:
            True if lock acquired, False if already locked by another worker
        """
        lock_key = f"{DISPATCH_LOCK_PREFIX}{task_id}"
        try:
            # SET NX with TTL - atomic operation
            result = self.redis.set(lock_key, "1", nx=True, ex=DISPATCH_LOCK_TTL)
            if result:
                logger.debug("Acquired dispatch lock", task_id=task_id)
                return True
            else:
                logger.debug("Dispatch lock already held", task_id=task_id)
                return False
        except redis.RedisError as e:
            logger.warning("Failed to acquire dispatch lock", task_id=task_id, error=str(e))
            return False

    def release_dispatch_lock(self, task_id: str) -> bool:
        """Release a distributed lock for task dispatch.

        Args:
            task_id: Task ID to unlock

        Returns:
            True if lock released, False on error
        """
        lock_key = f"{DISPATCH_LOCK_PREFIX}{task_id}"
        try:
            self.redis.delete(lock_key)
            logger.debug("Released dispatch lock", task_id=task_id)
            return True
        except redis.RedisError as e:
            logger.warning("Failed to release dispatch lock", task_id=task_id, error=str(e))
            return False

    def get_due_scheduled_tasks(self) -> list[DispatchEvent]:
        """Get scheduled tasks that are due for execution.

        Returns tasks with next_run <= now, removes them from the set.
        Uses distributed locking to prevent race conditions.
        """
        key = "summitflow:scheduled_tasks"
        now = datetime.now(UTC).timestamp()

        try:
            items_raw = self.redis.zrangebyscore(key, "-inf", now)
            items: list[Any] = list(items_raw) if items_raw else []  # type: ignore[arg-type]
            if not items:
                return []

            events: list[DispatchEvent] = []
            for item in items:
                try:
                    data: dict[str, Any] = json.loads(item)
                    event = DispatchEvent.from_dict(data)

                    # Acquire lock before processing to prevent race conditions
                    if not self.acquire_dispatch_lock(event.task_id):
                        logger.debug(
                            "Skipping task - already being processed",
                            task_id=event.task_id,
                        )
                        continue

                    events.append(event)
                    self.redis.zrem(key, item)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Failed to parse scheduled task", error=str(e))
                    self.redis.zrem(key, item)

            return events

        except redis.RedisError as e:
            logger.warning("Failed to get scheduled tasks", error=str(e))
            return []

    def subscribe(
        self,
        callback: Any,
        channels: list[str] | None = None,
    ) -> None:
        """Subscribe to dispatch events.

        Args:
            callback: Function to call with DispatchEvent
            channels: Channels to subscribe to (default: immediate dispatch only)
        """
        if channels is None:
            channels = [CHANNEL_TASK_DISPATCH]

        self._pubsub = self.redis.pubsub()  # type: ignore[no-untyped-call]
        self._pubsub.subscribe(*channels)
        self._running = True

        def listener() -> None:
            while self._running:
                try:
                    message = self._pubsub.get_message(timeout=1.0) if self._pubsub else None
                    if message and message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            event = DispatchEvent.from_dict(data)
                            callback(event)
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning("Failed to parse dispatch event", error=str(e))
                except redis.RedisError as e:
                    logger.warning("Redis subscription error", error=str(e))

        self._subscriber_thread = threading.Thread(target=listener, daemon=True)
        self._subscriber_thread.start()
        logger.info("Started dispatch event subscriber", channels=channels)

    def unsubscribe(self) -> None:
        """Stop subscribing to events."""
        self._running = False
        if self._pubsub:
            self._pubsub.unsubscribe()  # type: ignore[no-untyped-call]
            self._pubsub.close()
        if self._subscriber_thread:
            self._subscriber_thread.join(timeout=2.0)
        logger.info("Stopped dispatch event subscriber")

    def close(self) -> None:
        """Close Redis connection."""
        self.unsubscribe()
        if self._redis:
            self._redis.close()


_dispatcher: EventDispatcher | None = None


def get_dispatcher() -> EventDispatcher:
    """Get the singleton EventDispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = EventDispatcher()
    return _dispatcher
