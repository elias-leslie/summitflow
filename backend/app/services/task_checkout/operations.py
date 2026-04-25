"""Task branch checkout operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...logging_config import get_logger
from .checkpoint import create_checkpoint_metadata, remove_checkpoint_metadata
from .types import TaskCheckoutInfo

logger = get_logger(__name__)


def _project_root(project_id: str) -> Path | None:
    from ...storage.projects import get_project_root_path

    project_root = get_project_root_path(project_id)
    return Path(project_root).resolve() if project_root else None


def _task_branch(task_id: str) -> str:
    return f"{task_id}/main"


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _branch_exists(branch: str, cwd: Path) -> bool:
    result = _run_git(["rev-parse", "--verify", branch], cwd, check=False)
    return result.returncode == 0


def _current_branch(cwd: Path) -> str | None:
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, check=False)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def _checkout(branch: str, cwd: Path, create_from: str | None = None) -> None:
    args = ["checkout"]
    if create_from is not None:
        args.extend(["-b", branch, create_from])
    else:
        args.append(branch)
    _run_git(args, cwd)


def _resolve_base_branch(task_id: str, project_id: str) -> str:
    from cli.lib.checkpoint_metadata import load_snapshot_meta

    meta = load_snapshot_meta(task_id)
    if meta and meta.project_id == project_id and meta.base_branch:
        return meta.base_branch
    return "main"


def _build_checkout_info(task_id: str, project_root: Path, base_branch: str) -> TaskCheckoutInfo:
    return TaskCheckoutInfo(
        path=project_root,
        branch=_task_branch(task_id),
        task_id=task_id,
        base_branch=base_branch,
        is_active=True,
    )


def create_task_checkout(
    task_id: str,
    project_id: str,
    base_branch: str = "main",
) -> TaskCheckoutInfo | None:
    """Ensure a task branch exists and is checked out in the project root."""
    try:
        project_root = _project_root(project_id)
        if project_root is None:
            logger.warning("task_checkout_missing_project_root", task_id=task_id, project_id=project_id)
            return None

        branch = _task_branch(task_id)
        if _branch_exists(branch, project_root):
            if _current_branch(project_root) != branch:
                _checkout(branch, project_root)
            base_branch = _resolve_base_branch(task_id, project_id)
            create_checkpoint_metadata(
                task_id=task_id,
                project_id=project_id,
                base_branch=base_branch,
            )
            logger.info(
                "task_branch_reused",
                task_id=task_id,
                project_id=project_id,
                branch=branch,
                path=str(project_root),
            )
            return _build_checkout_info(task_id, project_root, base_branch)

        if _current_branch(project_root) != base_branch:
            _checkout(base_branch, project_root)
        _checkout(branch, project_root, create_from=base_branch)
        logger.info(
            "task_branch_created",
            task_id=task_id,
            project_id=project_id,
            path=str(project_root),
            branch=branch,
            base_branch=base_branch,
        )
        create_checkpoint_metadata(
            task_id=task_id,
            project_id=project_id,
            base_branch=base_branch,
        )
        return _build_checkout_info(task_id, project_root, base_branch)
    except Exception as e:
        logger.warning(
            "task_branch_creation_failed",
            task_id=task_id,
            project_id=project_id,
            error=str(e),
        )
        return None


def get_task_checkout(
    task_id: str, project_id: str | None = None
) -> TaskCheckoutInfo | None:
    """Return task branch info when the checkpoint branch exists."""
    try:
        if not project_id:
            return None
        project_root = _project_root(project_id)
        if project_root is None:
            return None
        branch = _task_branch(task_id)
        if not _branch_exists(branch, project_root):
            return None
        base_branch = _resolve_base_branch(task_id, project_id)
        return _build_checkout_info(task_id, project_root, base_branch)
    except Exception as e:
        logger.debug("task_branch_lookup_failed", task_id=task_id, project_id=project_id, error=str(e))
        return None


def remove_task_checkout(
    task_id: str, delete_branch: bool = False, project_id: str | None = None
) -> bool:
    """Remove checkpoint metadata and optionally delete the task branch."""
    try:
        project_root = _project_root(project_id) if project_id else None
        branch = _task_branch(task_id)
        if project_root and delete_branch and _branch_exists(branch, project_root):
            base_branch = _resolve_base_branch(task_id, project_id or "")
            if _current_branch(project_root) == branch and base_branch:
                _checkout(base_branch, project_root)
            _run_git(["branch", "-D", branch], project_root, check=False)
        if project_id:
            remove_checkpoint_metadata(task_id, project_id)
        logger.info(
            "task_branch_checkpoint_removed",
            task_id=task_id,
            project_id=project_id,
            branch_deleted=delete_branch,
        )
        return True
    except Exception as e:
        logger.warning("task_branch_removal_failed", task_id=task_id, project_id=project_id, error=str(e))
        return False


__all__ = [
    "create_task_checkout",
    "get_task_checkout",
    "remove_task_checkout",
]
