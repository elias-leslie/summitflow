"""Internal helpers for the git CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils._git_core import get_managed_repos as _get_managed_repos_from_db
from app.utils._git_core import get_repo_status as _get_repo_status_model
from app.utils._git_core import run_git as _run_git

ALREADY_UP_TO_DATE = "Already up to date"


def _get_managed_repos() -> list[Path]:
    """Get managed repos from the shared DB-backed git core helper."""
    return _get_managed_repos_from_db()


def _get_repo_status(repo_path: Path) -> dict[str, Any] | None:
    """Get status dict for a git repo, or None if not a valid repo."""
    status = _get_repo_status_model(repo_path)
    if status is None:
        return None
    return status.model_dump()


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
