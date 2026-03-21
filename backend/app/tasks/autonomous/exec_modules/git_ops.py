"""Git operations for task execution."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ....logging_config import get_logger
from ....utils.shared_paths import resolve_script

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


def _run_git(project_path: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a git command inside the project path."""
    return subprocess.run(
        ["git", *args],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

def _resolve_commit_script(project_path: str) -> str | None:
    """Resolve the canonical commit helper for this repo/worktree."""
    candidates: list[str] = []
    path_candidate = shutil.which("commit.sh")
    if path_candidate:
        candidates.append(path_candidate)

    repo_root = _run_git(project_path, "rev-parse", "--show-toplevel")
    if repo_root.returncode == 0 and repo_root.stdout.strip():
        candidates.append(str(Path(repo_root.stdout.strip()) / "scripts" / "commit.sh"))

    candidates.append(str(resolve_script("commit.sh")))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        if path.is_file() and path.stat().st_mode & 0o111:
            return str(path)
    return None


def _has_branch_commits(project_path: str) -> bool:
    """Return True when the current branch is ahead of main."""
    result = _run_git(project_path, "log", "--oneline", "main..HEAD")
    return bool(result.stdout and result.stdout.strip())


def has_unpublished_commits(project_path: str) -> bool:
    """Return True when HEAD contains local-only commits not on remote."""
    upstream = _run_git(
        project_path,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    if upstream.returncode != 0 or not upstream.stdout.strip():
        return _has_branch_commits(project_path)

    ahead = _run_git(
        project_path,
        "rev-list",
        "--count",
        f"{upstream.stdout.strip()}..HEAD",
    )
    if ahead.returncode != 0:
        return False
    return int((ahead.stdout or "0").strip() or "0") > 0


def publish_existing_commits(project_path: str) -> bool:
    """Push already-committed local work to remote when needed."""
    if not has_unpublished_commits(project_path):
        return True

    commit_sh = _resolve_commit_script(project_path)
    if not commit_sh:
        logger.warning("publish_existing_commits_missing_commit_sh")
        return False

    try:
        result = subprocess.run(
            [commit_sh, "--json", "--current", "--push"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0 and not has_unpublished_commits(project_path):
            logger.info("publish_existing_commits_success")
            return True
        logger.warning(
            "publish_existing_commits_failed",
            returncode=result.returncode,
            stderr=result.stderr[:200],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("publish_existing_commits_timeout")
        return False
    except Exception as e:
        logger.warning("publish_existing_commits_exception", error=str(e))
        return False


def smart_commit(
    project_path: str,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
) -> bool:
    """Preserve work via the canonical commit helper.

    Args:
        project_path: Path to the project/worktree
        message: Commit message
        task_id: Optional task ID to tag the commit
        push: Push immediately after commit
        skip_checks: Skip dt checks for checkpoint/recovery commits

    Returns:
        True if work is preserved successfully, False otherwise
    """
    if not has_uncommitted_changes(project_path):
        return True

    commit_sh = _resolve_commit_script(project_path)
    if not commit_sh:
        logger.warning("smart_commit_missing_commit_sh")
        return False

    args = [commit_sh, "--json", "--current", "--msg", message]
    if task_id:
        args.extend(["--task", task_id])
    if push:
        args.append("--push")
    else:
        args.append("--no-push")
    if skip_checks:
        args.append("--skip-checks")

    try:
        result = subprocess.run(
            args, cwd=project_path, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0 and (not push or not has_unpublished_commits(project_path)):
            logger.info("smart_commit_success", message=message[:80])
            return True

        logger.warning(
            "smart_commit_failed",
            returncode=result.returncode,
            stderr=result.stderr[:200],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("smart_commit_timeout")
        return False
    except Exception as e:
        logger.warning("smart_commit_exception", error=str(e))
        return False
