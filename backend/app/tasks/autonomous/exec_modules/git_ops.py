"""Git operations for task execution."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ....utils.shared_paths import get_repo_root

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
    """Resolve the canonical st command for git commit workflow."""
    candidates: list[str] = []
    path_candidate = shutil.which("st")
    if path_candidate:
        candidates.append(path_candidate)

    repo_root = _run_git(project_path, "rev-parse", "--show-toplevel")
    if repo_root.returncode == 0 and repo_root.stdout.strip():
        candidates.append(str(Path(repo_root.stdout.strip()) / "backend" / ".venv" / "bin" / "st"))

    candidates.append(str(get_repo_root() / "backend" / ".venv" / "bin" / "st"))

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
        logger.warning("publish_existing_commits_missing_st")
        return False

    try:
        result = subprocess.run(
            [commit_sh, "git", "commit", "--json", "--current", "--push"],
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


def _build_smart_commit_args(
    project_path: str,
    message: str,
    task_id: str,
    push: bool,
    skip_checks: bool,
) -> list[str] | None:
    """Build the canonical st git commit argv for the checkout."""
    commit_sh = _resolve_commit_script(project_path)
    if not commit_sh:
        return None

    args = [commit_sh, "git", "commit", "--json", "--current", "--msg", message]
    if task_id:
        args.extend(["--task", task_id])
    if push:
        args.append("--push")
    else:
        args.append("--no-push")
    if skip_checks:
        args.append("--skip-checks")
    return args



def _format_command(args: list[str]) -> str:
    """Return a shell-safe human-readable command string."""
    return " ".join(shlex.quote(arg) for arg in args)



def _build_commit_failure_detail(
    command_display: str,
    *,
    returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
    note: str | None = None,
) -> str:
    """Build a concise operator-facing failure detail for commit helper failures."""
    parts = [f"commit helper failed: {command_display}"]
    if returncode is not None:
        parts.append(f"returncode: {returncode}")
    if note:
        parts.append(note)
    stdout_text = stdout.strip()
    stderr_text = stderr.strip()
    if stdout_text:
        parts.append(f"stdout: {stdout_text[:400]}")
    if stderr_text:
        parts.append(f"stderr: {stderr_text[:400]}")
    return "; ".join(parts)



def smart_commit_result(
    project_path: str,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
) -> dict[str, Any]:
    """Run the canonical commit helper and preserve failure detail."""
    if not has_uncommitted_changes(project_path):
        return {
            "success": True,
            "command": [],
            "command_display": "",
            "returncode": 0,
            "detail": "",
            "stdout": "",
            "stderr": "",
        }

    args = _build_smart_commit_args(project_path, message, task_id, push, skip_checks)
    if not args:
        logger.warning("smart_commit_missing_st")
        return {
            "success": False,
            "command": [],
            "command_display": "",
            "returncode": None,
            "detail": "commit helper failed: st could not be resolved",
            "stdout": "",
            "stderr": "",
        }

    command_display = _format_command(args)
    try:
        result = subprocess.run(
            args,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        published = True
        if result.returncode == 0 and push:
            published = not has_unpublished_commits(project_path)
        if result.returncode == 0 and published:
            logger.info("smart_commit_success", message=message[:80])
            return {
                "success": True,
                "command": args,
                "command_display": command_display,
                "returncode": result.returncode,
                "detail": "",
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        detail = _build_commit_failure_detail(
            command_display,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            note=None if published else "branch still has unpublished commits after helper completed",
        )
        logger.warning(
            "smart_commit_failed",
            returncode=result.returncode,
            stderr=result.stderr[:200],
        )
        return {
            "success": False,
            "command": args,
            "command_display": command_display,
            "returncode": result.returncode,
            "detail": detail,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        logger.warning("smart_commit_timeout")
        detail = _build_commit_failure_detail(
            command_display,
            note=f"timed out after {exc.timeout}s",
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
        )
        return {
            "success": False,
            "command": args,
            "command_display": command_display,
            "returncode": None,
            "detail": detail,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
        }
    except Exception as e:
        logger.warning("smart_commit_exception", error=str(e))
        return {
            "success": False,
            "command": args,
            "command_display": command_display,
            "returncode": None,
            "detail": f"commit helper failed: {command_display}; exception: {e}",
            "stdout": "",
            "stderr": str(e),
        }



def smart_commit(
    project_path: str,
    message: str,
    task_id: str = "",
    push: bool = True,
    skip_checks: bool = False,
) -> bool:
    """Preserve work via the canonical commit helper.

    Args:
        project_path: Path to the project checkout
        message: Commit message
        task_id: Optional task ID to tag the commit
        push: Push immediately after commit
        skip_checks: Skip dt checks for checkpoint/recovery commits

    Returns:
        True if work is preserved successfully, False otherwise
    """
    return bool(
        smart_commit_result(
            project_path,
            message,
            task_id=task_id,
            push=push,
            skip_checks=skip_checks,
        ).get("success")
    )
