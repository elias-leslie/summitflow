"""Agent Pool for managing concurrent task execution.

Provides:
- Configurable concurrency pool with default size 3
- File overlap detection to prevent conflicts
- Priority + FIFO queue ordering
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_POOL_SIZE = 3


@dataclass
class TaskQueueEntry:
    """Entry in the execution queue."""

    task_id: str
    project_id: str
    priority: int = 2
    files_to_modify: list[str] = field(default_factory=list)
    queued_at: float = 0.0

    def __lt__(self, other: TaskQueueEntry) -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.queued_at < other.queued_at


class FileOverlapDetector:
    """Detects file overlap between tasks to prevent conflicts."""

    def __init__(self) -> None:
        self._active_files: dict[str, str] = {}

    def register_task_files(self, task_id: str, files: list[str]) -> None:
        """Register files being modified by a task."""
        for f in files:
            self._active_files[f] = task_id

    def unregister_task_files(self, task_id: str) -> None:
        """Unregister files when task completes."""
        self._active_files = {f: tid for f, tid in self._active_files.items() if tid != task_id}

    def detect_overlap(self, files_to_modify: list[str]) -> list[tuple[str, str]]:
        """Detect which files overlap with currently active tasks.

        Returns list of (file_path, blocking_task_id) tuples.
        """
        overlaps: list[tuple[str, str]] = []
        for f in files_to_modify:
            if f in self._active_files:
                overlaps.append((f, self._active_files[f]))
        return overlaps

    def has_conflict(self, files_to_modify: list[str]) -> bool:
        """Check if any files would conflict with active tasks."""
        return len(self.detect_overlap(files_to_modify)) > 0


class AgentPool:
    """Manages concurrent task execution with configurable pool size.

    Features:
    - Configurable max_concurrent from project settings (default 3)
    - File overlap detection to prevent conflicts
    - Priority + FIFO queue ordering
    """

    def __init__(self, max_concurrent: int | None = None, pool_size: int | None = None) -> None:
        """Initialize the agent pool.

        Args:
            max_concurrent: Maximum concurrent executions (alias for pool_size)
            pool_size: Maximum concurrent executions (preferred name)
        """
        self.max_concurrent = pool_size or max_concurrent or DEFAULT_POOL_SIZE
        self._active_tasks: set[str] = set()
        self._queue: list[TaskQueueEntry] = []
        self._overlap_detector = FileOverlapDetector()

    @property
    def pool_size(self) -> int:
        """Current pool size (max concurrent tasks)."""
        return self.max_concurrent

    def has_capacity(self) -> bool:
        """Check if pool has capacity for more tasks."""
        return len(self._active_tasks) < self.max_concurrent

    def get_active_count(self) -> int:
        """Get count of currently active tasks."""
        return len(self._active_tasks)

    def enqueue(
        self,
        task_id: str,
        project_id: str,
        priority: int = 2,
        files_to_modify: list[str] | None = None,
    ) -> None:
        """Add task to execution queue."""
        import time

        entry = TaskQueueEntry(
            task_id=task_id,
            project_id=project_id,
            priority=priority,
            files_to_modify=files_to_modify or [],
            queued_at=time.time(),
        )
        self._queue.append(entry)
        self._queue.sort()
        logger.info(
            "Task enqueued", task_id=task_id, priority=priority, queue_size=len(self._queue)
        )

    def get_next_safe(self) -> TaskQueueEntry | None:
        """Get next task that is safe to execute (no file conflicts).

        Returns highest priority task without file conflicts, or None.
        """
        if not self.has_capacity():
            return None

        for i, entry in enumerate(self._queue):
            if not self._overlap_detector.has_conflict(entry.files_to_modify):
                self._queue.pop(i)
                self._active_tasks.add(entry.task_id)
                self._overlap_detector.register_task_files(entry.task_id, entry.files_to_modify)
                logger.info(
                    "Task dequeued for execution",
                    task_id=entry.task_id,
                    active_count=len(self._active_tasks),
                )
                return entry

        return None

    def mark_complete(self, task_id: str) -> None:
        """Mark task as complete, freeing its slot and files."""
        self._active_tasks.discard(task_id)
        self._overlap_detector.unregister_task_files(task_id)
        logger.info(
            "Task completed in pool",
            task_id=task_id,
            active_count=len(self._active_tasks),
        )

    def get_queue_status(self) -> dict[str, Any]:
        """Get current queue status."""
        return {
            "active_tasks": list(self._active_tasks),
            "active_count": len(self._active_tasks),
            "queued_count": len(self._queue),
            "max_concurrent": self.max_concurrent,
            "has_capacity": self.has_capacity(),
        }

    def skip_conflict(self, task_id: str) -> bool:
        """Skip a task due to conflict (move to end of queue).

        Returns True if task was found and moved.
        """
        for i, entry in enumerate(self._queue):
            if entry.task_id == task_id:
                entry = self._queue.pop(i)
                entry.priority += 1
                self._queue.append(entry)
                self._queue.sort()
                logger.info("Task skipped due to conflict", task_id=task_id)
                return True
        return False


_global_pool: AgentPool | None = None


def get_agent_pool(max_concurrent: int | None = None) -> AgentPool:
    """Get or create the global agent pool instance."""
    global _global_pool
    if _global_pool is None:
        _global_pool = AgentPool(max_concurrent=max_concurrent or DEFAULT_POOL_SIZE)
    return _global_pool
