"""Execution interruption helpers for safe pause/stop checkpoints."""

from __future__ import annotations

from ....storage import tasks as task_store
from .events import emit_log


class ExecutionInterrupted(Exception):
    """Raised when task execution should pause or stop at a checkpoint."""

    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        self.reason = reason
        super().__init__(reason)


_INTERRUPT_STATUSES = {"cancelled", "completed", "failed"}


def assert_task_runnable(task_id: str, project_id: str, checkpoint: str) -> None:
    """Raise when a task has been externally paused or stopped."""
    task = task_store.get_task(task_id)
    if not task:
        raise ExecutionInterrupted("failed", "task_missing")

    status = str(task.get("status"))
    if status not in _INTERRUPT_STATUSES:
        return

    emit_log(
        task_id,
        "info",
        f"Execution checkpoint reached: {checkpoint}; task status is {status}",
        source="orchestrator",
        project_id=project_id,
    )
    raise ExecutionInterrupted(status, f"task_status={status}")
