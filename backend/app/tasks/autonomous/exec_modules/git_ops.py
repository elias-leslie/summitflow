"""Git operations for task execution."""

from __future__ import annotations

import shutil
import subprocess

from ....logging_config import get_logger

logger = get_logger(__name__)


def has_uncommitted_changes(project_path: str) -> bool:
    """Check if the working tree has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return bool(result.stdout.strip())


def auto_commit(project_path: str, message: str) -> bool:
    """Auto-commit all changes with the given message.

    Returns True if commit was made, False if nothing to commit or error.
    """
    try:
        add_result = subprocess.run(
            ["git", "add", "-A"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if add_result.returncode != 0:
            logger.warning("git_add_failed", error=add_result.stderr)
            return False

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if commit_result.returncode != 0:
            if "nothing to commit" in commit_result.stdout.lower():
                return False
            logger.warning("git_commit_failed", error=commit_result.stderr)
            return False

        logger.info("auto_commit_success", message=message[:80])
        return True
    except Exception as e:
        logger.warning("auto_commit_exception", error=str(e))
        return False


def _raw_push(project_path: str) -> bool:
    """Push current branch when commit.sh is unavailable."""
    try:
        result = subprocess.run(
            ["git", "push"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("raw_push_success")
            return True
        logger.warning("raw_push_failed", error=result.stderr[:200])
        return False
    except Exception as e:
        logger.warning("raw_push_exception", error=str(e))
        return False


def smart_commit(project_path: str, message: str, task_id: str = "", push: bool = False) -> bool:
    """Commit using commit.sh which runs quality gates.

    Falls back to auto_commit if commit.sh is not available.

    Args:
        project_path: Path to the project/worktree
        message: Commit message
        task_id: Optional task ID to tag the commit
        push: Push immediately after commit when the change belongs on main

    Returns:
        True if commit was made, False otherwise
    """
    commit_sh = shutil.which("commit.sh")
    if not commit_sh:
        committed = auto_commit(project_path, message)
        return committed and (not push or _raw_push(project_path))

    args = [commit_sh, "--json", "--msg", message]
    if task_id:
        args.extend(["--task", task_id])
    if push:
        args.append("--push")

    try:
        result = subprocess.run(
            args, cwd=project_path, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            logger.info("smart_commit_success", message=message[:80])
            return True

        logger.warning(
            "smart_commit_failed",
            returncode=result.returncode,
            stderr=result.stderr[:200],
        )
        committed = auto_commit(project_path, message)
        return committed and (not push or _raw_push(project_path))
    except subprocess.TimeoutExpired:
        logger.warning("smart_commit_timeout")
        committed = auto_commit(project_path, message)
        return committed and (not push or _raw_push(project_path))
    except Exception as e:
        logger.warning("smart_commit_exception", error=str(e))
        committed = auto_commit(project_path, message)
        return committed and (not push or _raw_push(project_path))
