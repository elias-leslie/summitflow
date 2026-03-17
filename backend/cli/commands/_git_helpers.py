"""Internal helpers for the git CLI commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.config import DEFAULT_API_BASE

FALLBACK_FILE = Path.home() / ".claude/config/managed-repos.txt"
REMOTE_REF_TEMPLATE = "{branch}...origin/{branch}"
ALREADY_UP_TO_DATE = "Already up to date"


def _get_summitflow_api_url() -> str:
    return f"{os.getenv('ST_API_BASE', DEFAULT_API_BASE)}/projects"


def _get_backup_sources_api_url() -> str:
    return f"{os.getenv('ST_API_BASE', DEFAULT_API_BASE)}/backup-sources"


def _is_valid_git_path(path: Path) -> bool:
    return path.exists() and (path / ".git").exists()


def _repos_from_api() -> list[Path]:
    repos: list[Path] = []

    projects_response = httpx.get(_get_summitflow_api_url(), timeout=2.0)
    if projects_response.status_code == 200:
        repos.extend([
        Path(p["root_path"])
        for p in projects_response.json()
        if p.get("root_path") and _is_valid_git_path(Path(p["root_path"]))
        ])

    sources_response = httpx.get(_get_backup_sources_api_url(), timeout=2.0)
    if sources_response.status_code == 200:
        repos.extend([
            Path(source["path"])
            for source in sources_response.json()
            if source.get("path")
            and source.get("source_type") in {"config", "workspace"}
            and _is_valid_git_path(Path(source["path"]))
        ])

    deduped: list[Path] = []
    for repo in repos:
        if repo not in deduped:
            deduped.append(repo)
    return deduped


def _repos_from_fallback() -> list[Path]:
    if not FALLBACK_FILE.exists():
        return []
    repos = []
    for raw in FALLBACK_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path = Path(line).expanduser()
        if _is_valid_git_path(path):
            repos.append(path)
    return repos


def _get_managed_repos() -> list[Path]:
    """Get managed repos from API, falling back to the local managed-repos file."""
    try:
        repos = _repos_from_api()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
        repos = _repos_from_fallback()
    else:
        for repo in _repos_from_fallback():
            if repo not in repos:
                repos.append(repo)
    return repos


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


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
