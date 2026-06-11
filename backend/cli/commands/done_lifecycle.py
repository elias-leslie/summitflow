from __future__ import annotations

from app.storage.projects import get_project_root_path
from app.utils.git_base import normalize_base_branch

from .._client_base import APIError
from ..client import STClient
from ..lib.checkpoint import get_snapshot_info
from ..lib.checkpoint_metadata import SnapshotMeta, save_snapshot_meta
from ..output import output_warning


def _reconstruct_snapshot_info(
    client: STClient,
    task_id: str,
) -> dict[str, str | int | None] | None:
    """Attempt to reconstruct checkpoint metadata from task API and legacy task refs.

    When the .meta.json file is missing but the task is still active and the
    legacy task ref exists, rebuild the metadata so ``st done`` can proceed.
    """
    from ..lib.checkpoint_branches import get_task_branches

    try:
        task = client.get_task(task_id)
    except APIError:
        return None

    project_id = task.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        return None

    # Recovered legacy refs may still be pending but need closeout.
    if task.get("status") not in ("in_progress", "claimed", "pending"):
        return None

    branches = get_task_branches(task_id, project_id=project_id)
    task_ref = next((branch for branch in branches if branch.get("type") == "task"), None)
    if not task_ref:
        return None

    project_root = get_project_root_path(project_id)
    base_branch = task.get("base_branch")
    if not isinstance(base_branch, str) or not base_branch:
        base_branch = "main"
    base_branch = normalize_base_branch(base_branch, project_root)

    # Rebuild and persist the metadata so future commands work too.
    meta = SnapshotMeta(
        task_id=task_id,
        project_id=project_id,
        base_branch=base_branch,
        created_at=task.get("created_at", ""),
        claimed_by=task.get("claimed_by", "unknown"),
    )
    save_snapshot_meta(meta)
    output_warning(
        f"Checkpoint metadata was missing for {task_id} — reconstructed from legacy task ref."
    )
    return get_snapshot_info(task_id)
