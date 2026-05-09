"""Checkout health checking and project path utilities."""

from __future__ import annotations

import subprocess
from json import JSONDecodeError, loads
from pathlib import Path

from ....logging_config import get_logger
from ....services.task_checkout import get_execution_path
from ....storage.projects import get_project_root_path
from .events import emit_log

logger = get_logger(__name__)


def _expected_task_branch(task_id: str) -> str:
    """Return the canonical shared-checkout branch name for a task."""
    return f"{task_id}/main"


def _current_branch(project_path: str) -> str | None:
    """Return current branch for the shared checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def _parse_dirty_paths(status_output: str) -> list[str]:
    """Parse `git status --porcelain` output into file paths."""
    paths: list[str] = []
    for raw_line in status_output.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        path_field = line[3:]
        if " -> " in path_field:
            path_field = path_field.split(" -> ", 1)[1]
        if path_field:
            paths.append(path_field)
    return paths


def _load_main_repo_dirty_baseline(task_id: str, project_id: str, main_root: str) -> list[str]:
    """Load the dirty-file baseline captured when the checkpoint was created."""
    meta_path = Path(main_root) / ".st" / "snapshots" / f"{task_id}.meta.json"
    if not meta_path.exists():
        return []
    try:
        meta = loads(meta_path.read_text())
    except (OSError, JSONDecodeError) as e:
        logger.warning(
            "main_repo_dirty_baseline_load_failed",
            task_id=task_id,
            project_id=project_id,
            path=str(meta_path),
            error=str(e),
        )
        return []

    baseline = meta.get("main_repo_dirty_paths")
    if not isinstance(baseline, list):
        return []
    return [str(path) for path in baseline if str(path)]


def get_project_path(project_id: str, task_id: str | None = None) -> str:
    """Get execution path for task.

    Args:
        project_id: Project ID for fallback to root path
        task_id: Task ID to resolve branch checkout context (optional)

    Returns:
        Project root path

    Raises:
        ValueError: If project has no root_path configured
    """
    if task_id:
        return get_execution_path(task_id, project_id)

    # Fallback for cases without task_id (e.g., pristine checks)
    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")
    return project_root


def get_checkout_health_failure(project_path: str, task_id: str, project_id: str) -> str | None:
    """Return why the shared checkout is invalid, or None when healthy.

    Returns:
        None if healthy, otherwise a human-readable failure reason.
    """
    path = Path(project_path)
    if not path.is_dir():
        reason = f"CHECKOUT GONE: {project_path} removed during execution"
        emit_log(task_id, "error", reason, source="orchestrator", project_id=project_id)
        return reason
    if not (path / ".git").exists():
        reason = f"CHECKOUT CORRUPTED: {project_path} not a git checkout"
        emit_log(task_id, "error", reason, source="orchestrator", project_id=project_id)
        return reason
    current_branch = _current_branch(project_path)
    expected_branch = _expected_task_branch(task_id)
    if current_branch != expected_branch:
        reason = (
            f"CHECKOUT BRANCH MISMATCH: expected {expected_branch}, "
            f"got {current_branch or 'unknown'}"
        )
        emit_log(task_id, "error", reason, source="orchestrator", project_id=project_id)
        return reason
    return None


def check_checkout_health(project_path: str, task_id: str, project_id: str) -> bool:
    """Check the shared checkout is still a valid git working directory."""
    return get_checkout_health_failure(project_path, task_id, project_id) is None


def check_main_repo_leakage(
    task_id: str, project_id: str, project_path: str,
) -> bool:
    """Detect writes outside the starting dirty baseline.

    In the shared-checkout model this only matters when execution somehow runs
    outside the canonical project root, which should not happen.
    """
    main_root = get_project_root_path(project_id)
    if not main_root or main_root == project_path:
        return False

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=main_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        baseline_paths = set(_load_main_repo_dirty_baseline(task_id, project_id, main_root))
        dirty_paths = _parse_dirty_paths(result.stdout)
        leaked_paths = [path for path in dirty_paths if path not in baseline_paths]
        if leaked_paths:
            leaked_preview = "\n".join(f" M {path}" for path in leaked_paths[:10])
            cause_hint = (
                "new dirty paths appeared beyond the starting baseline"
                if baseline_paths else
                "dirty paths appeared while no starting baseline was recorded"
            )
            emit_log(
                task_id,
                "warn",
                f"CHECKOUT LEAKAGE: Main repo dirt changed during task-branch execution; {cause_hint}. "
                f"Files: {leaked_preview[:200]}",
                source="orchestrator",
                project_id=project_id,
            )
            return True
    except Exception as e:
        logger.warning("main_repo_leakage_check_failed", error=str(e))

    return False
