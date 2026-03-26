from __future__ import annotations

from .._client_base import APIError
from ..client import STClient
from ..lib.checkpoint import get_snapshot_info
from ..lib.checkpoint_metadata import SnapshotMeta, save_snapshot_meta
from ..output import output_warning


def _trigger_health_check(task_id: str, project_id: str | None) -> None:
    if not project_id:
        return
    try:
        from ._api_paths import SITE_HEALTH_CHECK_TRIGGER_PATH
        from .memory_api import agent_hub_request

        agent_hub_request(
            "POST",
            SITE_HEALTH_CHECK_TRIGGER_PATH,
            json={"project_id": project_id, "task_id": task_id},
            tool_name="st done",
        )
    except Exception:
        pass  # Never block completion on health check trigger failure


def _reconstruct_snapshot_info(
    client: STClient,
    task_id: str,
) -> dict[str, str | int | None] | None:
    """Attempt to reconstruct checkpoint metadata from task API and worktree.

    When the .meta.json file is missing but the task is claimed and a worktree
    still exists, rebuild the metadata so ``st done`` can proceed.
    """
    from ..lib.worktree import get_worktree_info

    try:
        task = client.get_task(task_id)
    except APIError:
        return None

    project_id = task.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        return None

    # Only recover for tasks that are actually in progress.
    if task.get("status") not in ("in_progress", "claimed"):
        return None

    wt_info = get_worktree_info(task_id, project_id)
    if not wt_info:
        return None

    # Rebuild and persist the metadata so future commands work too.
    meta = SnapshotMeta(
        task_id=task_id,
        project_id=project_id,
        base_branch=wt_info.base_branch or "main",
        created_at=task.get("created_at", ""),
        claimed_by=task.get("claimed_by", "unknown"),
        worktree_path=str(wt_info.path),
    )
    save_snapshot_meta(meta)
    output_warning(
        f"Checkpoint metadata was missing for {task_id} — reconstructed from worktree."
    )
    return get_snapshot_info(task_id)
