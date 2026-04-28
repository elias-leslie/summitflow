"""Internal helpers for the git CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils._git_core import get_managed_repos as _get_managed_repos_from_db
from app.utils._git_core import run_git as _run_git

from ..lib.jj import JJError, is_colocated, status_summary

REMOTE_REF_TEMPLATE = "{branch}...origin/{branch}"
ALREADY_UP_TO_DATE = "Already up to date"


def _is_valid_git_path(path: Path) -> bool:
    return path.exists() and (path / ".git").exists()


def _get_managed_repos() -> list[Path]:
    """Get managed repos from the shared DB-backed git core helper."""
    return _get_managed_repos_from_db()


def _get_ahead_behind(repo_path: Path, branch: str) -> tuple[int, int]:
    result = _run_git(["rev-list", "--left-right", "--count", REMOTE_REF_TEMPLATE.format(branch=branch)], repo_path)
    if result.returncode != 0:
        return 0, 0
    parts = result.stdout.strip().split()
    return (int(parts[0]), int(parts[1])) if len(parts) == 2 else (0, 0)


def _determine_state(uncommitted: int, behind: int, ahead: int) -> str:
    if uncommitted > 0:
        return "dirty"
    if behind > 0:
        return "behind"
    if ahead > 0:
        return "ahead"
    return "clean"


def _get_repo_status(repo_path: Path) -> dict[str, Any] | None:
    """Get status dict for a git repo, or None if not a valid repo."""
    if not _is_valid_git_path(repo_path):
        return None
    if is_colocated(repo_path):
        try:
            jj_status = status_summary(repo_path)
        except JJError:
            pass
        else:
            git_ahead, behind = _get_ahead_behind(repo_path, jj_status.branch)
            uncommitted = 0 if jj_status.state in {"clean", "unpublished"} else 1
            ahead = max(git_ahead, jj_status.unpublished)
            return {
                "path": str(repo_path),
                "name": repo_path.name,
                "branch": jj_status.branch,
                "uncommitted": uncommitted,
                "ahead": ahead,
                "behind": behind,
                "state": _determine_state(uncommitted, behind, ahead),
            }
    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if branch_result.returncode != 0:
        return None
    branch = branch_result.stdout.strip()
    porcelain = _run_git(["status", "--porcelain"], repo_path)
    uncommitted = len([ln for ln in porcelain.stdout.strip().split("\n") if ln]) if porcelain.returncode == 0 else 0
    ahead, behind = _get_ahead_behind(repo_path, branch)
    return {
        "path": str(repo_path),
        "name": repo_path.name,
        "branch": branch,
        "uncommitted": uncommitted,
        "ahead": ahead,
        "behind": behind,
        "state": _determine_state(uncommitted, behind, ahead),
    }


def _format_compact_repo(repo: dict[str, Any]) -> str:
    """Format repo status as compact one-liner."""
    name = repo.get("name", "?")[:15].ljust(15)
    branch = repo.get("branch", "?")[:15].ljust(15)
    state = repo.get("state", "?")[:7].ljust(7)
    return f"{name} {branch} {state} uncommitted:{repo.get('uncommitted',0)} ahead:{repo.get('ahead',0)} behind:{repo.get('behind',0)}"


def _sync_repo(repo_path: Path, repo_status: dict[str, Any]) -> dict[str, Any]:
    """Sync a single repo by pulling. Returns result dict."""
    result: dict[str, Any] = {"path": str(repo_path), "name": repo_path.name, "branch": repo_status.get("branch", "unknown")}
    if repo_status.get("uncommitted", 0) > 0:
        return {**result, "status": "skipped", "reason": "uncommitted changes"}
    git_result = _run_git(["pull", "--ff-only"], repo_path)
    if git_result.returncode == 0:
        result["status"] = "up_to_date" if ALREADY_UP_TO_DATE in git_result.stdout else "updated"
        if result["status"] == "updated":
            result["output"] = git_result.stdout.strip()
    else:
        result["status"] = "failed"
        result["error"] = git_result.stderr.strip()
    return result


def _print_sync_compact(results: list[dict[str, Any]]) -> None:
    """Print sync results in compact TOON format."""
    success = sum(1 for r in results if r["status"] in ("up_to_date", "updated"))
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"SYNC[{len(results)}] success:{success} failed:{failed} skipped:{skipped}")
    for r in results:
        print(f"{r['name'][:15].ljust(15)} {r['status'][:10].ljust(10)} {r.get('reason', r.get('error', ''))[:30]}")
