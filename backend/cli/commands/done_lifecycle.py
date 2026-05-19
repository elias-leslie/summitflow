from __future__ import annotations

import subprocess

from app.storage.projects import get_project_root_path
from app.utils.git_base import normalize_base_branch

from .._client_base import APIError
from ..client import STClient
from ..lib.checkpoint import get_snapshot_info
from ..lib.checkpoint_metadata import SnapshotMeta, save_snapshot_meta
from ..lib.project_config import load_services_config
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


def _task_branch_touched_frontend(
    task_id: str,
    project_id: str | None,
    *,
    base_branch: str = "main",
    base_commit: str | None = None,
) -> bool:
    """Return True when task work touched the project's configured frontend tree."""
    if not project_id:
        return False

    project_root = get_project_root_path(project_id)
    if not project_root:
        return False
    base_branch = normalize_base_branch(base_branch, project_root)

    frontend_service = load_services_config(project_root).get_service("frontend")
    frontend_cwd = str(getattr(frontend_service, "cwd", "") or "").strip().strip("/")
    if not frontend_cwd:
        return False

    if base_commit:
        diff_ref = f"{base_commit}..HEAD"
    else:
        from ..lib.checkpoint_branches import resolve_task_branch

        task_branch = resolve_task_branch(task_id, project_id=project_id)
        diff_ref = f"{base_branch}...{task_branch}"
    result = subprocess.run(
        ["git", "diff", "--name-only", diff_ref],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False

    prefix = f"{frontend_cwd}/"
    changed_paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return any(path == frontend_cwd or path.startswith(prefix) for path in changed_paths)


def _reconstruct_snapshot_info(
    client: STClient,
    task_id: str,
) -> dict[str, str | int | None] | None:
    """Attempt to reconstruct checkpoint metadata from task API and task branch.

    When the .meta.json file is missing but the task is still active and the
    task branch exists, rebuild the metadata so ``st done`` can proceed.
    """
    from ..lib.checkpoint_branches import get_task_branches

    try:
        task = client.get_task(task_id)
    except APIError:
        return None

    project_id = task.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        return None

    # Recovered orphan branches may still be pending but need closeout.
    if task.get("status") not in ("in_progress", "claimed", "pending"):
        return None

    branches = get_task_branches(task_id, project_id=project_id)
    task_branch = next((branch for branch in branches if branch.get("type") == "task"), None)
    if not task_branch:
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
        f"Checkpoint metadata was missing for {task_id} — reconstructed from task branch."
    )
    return get_snapshot_info(task_id)
