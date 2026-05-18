"""Checkpoint cleanup operations for completed or cancelled tasks."""

from __future__ import annotations

from typing import Literal, TypedDict

from ....logging_config import get_logger

logger = get_logger(__name__)


class CheckpointCleanupSuccess(TypedDict):
    """Successful checkpoint cleanup result."""

    task_id: str
    status: Literal["cleaned"]


class CheckpointCleanupSkipped(TypedDict):
    """Skipped checkpoint cleanup result."""

    task_id: str
    status: Literal["skipped"]
    reason: str


class CheckpointCleanupFailed(TypedDict):
    """Failed checkpoint cleanup result."""

    task_id: str
    status: Literal["failed", "error"]
    reason: str | None
    error: str | None


CheckpointCleanupResult = (
    CheckpointCleanupSuccess | CheckpointCleanupSkipped | CheckpointCleanupFailed
)


def cleanup_task_checkpoint(
    task_id: str,
    delete_branch: bool = False,
    project_id: str | None = None,
) -> CheckpointCleanupResult:
    """Remove checkpoint metadata for a completed or cancelled task.

    With task branches retired, this is just a small wrapper around the global
    checkpoint metadata store: delete the meta json so `st checkpoints` /
    `st cleanup` no longer show the task as active.

    Args:
        task_id: Task ID whose checkpoint metadata should be removed.
        delete_branch: Unused; retained for call-site compatibility.
        project_id: Project scope for the checkpoint metadata file.

    Returns:
        Dict with cleanup result.
    """
    del delete_branch

    try:
        from cli.lib.checkpoint_metadata import get_meta_path

        if not project_id:
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "missing_project_id",
            }

        meta_path = get_meta_path(task_id, project_id=project_id)
        if not meta_path.exists():
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "no_checkpoint",
            }

        meta_path.unlink()
        logger.info(
            "Cleaned up checkpoint metadata for task %s",
            task_id,
            extra={"task_id": task_id, "project_id": project_id},
        )
        return {
            "task_id": task_id,
            "status": "cleaned",
        }
    except Exception as e:
        logger.error("Error cleaning up checkpoint for task %s: %s", task_id, e)
        return {
            "task_id": task_id,
            "status": "error",
            "reason": None,
            "error": str(e),
        }
