"""Git management commands for the CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from ..config import get_config
from ..output import is_compact, output_error, output_json

app = typer.Typer(help="Git repository management")

# SummitFlow API for dynamic repo discovery
SUMMITFLOW_API = "http://localhost:8001/api/projects"

# Config repos always included (not SummitFlow projects)
CONFIG_REPOS = [Path.home() / ".claude"]

# Fallback file when API unavailable
FALLBACK_FILE = Path.home() / ".claude/config/managed-repos.txt"


def _get_managed_repos() -> list[Path]:
    """Get list of managed repos from SummitFlow API + config repos.

    Priority:
    1. SummitFlow API projects (root_path field)
    2. Fallback to static config file if API unavailable
    3. Always include CONFIG_REPOS (e.g., ~/.claude)

    Returns:
        List of Path objects for repos with valid .git directories.
    """
    repos: list[Path] = []

    # Try SummitFlow API first
    try:
        response = httpx.get(SUMMITFLOW_API, timeout=2.0)
        if response.status_code == 200:
            projects = response.json()
            for project in projects:
                root_path = project.get("root_path")
                if root_path:
                    path = Path(root_path)
                    if path.exists() and (path / ".git").exists():
                        repos.append(path)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
        # API unavailable - fall back to static config file
        if FALLBACK_FILE.exists():
            for line in FALLBACK_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                path = Path(line).expanduser()
                if path.exists() and (path / ".git").exists():
                    repos.append(path)

    # Always include config repos
    for config_repo in CONFIG_REPOS:
        if config_repo.exists() and (config_repo / ".git").exists() and config_repo not in repos:
            repos.append(config_repo)

    return repos


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _get_repo_status(repo_path: Path) -> dict[str, Any] | None:
    """Get status information for a git repository.

    Returns:
        Dict with branch, uncommitted, behind, ahead, or None if not a git repo.
    """
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return None

    status: dict[str, Any] = {
        "path": str(repo_path),
        "name": repo_path.name,
    }

    # Get current branch
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if result.returncode != 0:
        return None
    status["branch"] = result.stdout.strip()

    # Get uncommitted changes count
    result = _run_git(["status", "--porcelain"], repo_path)
    if result.returncode == 0:
        lines = [line for line in result.stdout.strip().split("\n") if line]
        status["uncommitted"] = len(lines)
    else:
        status["uncommitted"] = 0

    # Get ahead/behind counts (requires remote tracking)
    result = _run_git(
        ["rev-list", "--left-right", "--count", f"{status['branch']}...origin/{status['branch']}"],
        repo_path,
    )
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            status["ahead"] = int(parts[0])
            status["behind"] = int(parts[1])
        else:
            status["ahead"] = 0
            status["behind"] = 0
    else:
        status["ahead"] = 0
        status["behind"] = 0

    # Determine overall state
    if status["uncommitted"] > 0:
        status["state"] = "dirty"
    elif status["behind"] > 0:
        status["state"] = "behind"
    elif status["ahead"] > 0:
        status["state"] = "ahead"
    else:
        status["state"] = "clean"

    return status


def _format_compact_repo(repo: dict[str, Any]) -> str:
    """Format repository status as compact one-liner.

    Format: <name:15> <branch:15> <state:7> uncommitted:<n> ahead:<n> behind:<n>
    """
    name = repo.get("name", "?")[:15].ljust(15)
    branch = repo.get("branch", "?")[:15].ljust(15)
    state = repo.get("state", "?")[:7].ljust(7)
    uncommitted = repo.get("uncommitted", 0)
    ahead = repo.get("ahead", 0)
    behind = repo.get("behind", 0)
    return f"{name} {branch} {state} uncommitted:{uncommitted} ahead:{ahead} behind:{behind}"


@app.command()
def status(
    _all_repos: Annotated[
        bool,
        typer.Option("--all", "-a", help="Show all known managed repos"),
    ] = True,
) -> None:
    """Show git status for managed repositories.

    Displays status in TOON format when --compact is used:
    GIT[N]
    <name> <branch> <state> uncommitted:N ahead:N behind:N

    Examples:
        st git status
        st --compact git status
    """
    repos: list[dict[str, Any]] = []

    for repo_path in _get_managed_repos():
        repo_status = _get_repo_status(repo_path)
        if repo_status:
            repos.append(repo_status)

    if is_compact():
        print(f"GIT[{len(repos)}]")
        for repo in repos:
            print(_format_compact_repo(repo))
    else:
        output_json({"repositories": repos, "total": len(repos)})


@app.command()
def sync(
    _pull_only: Annotated[
        bool,
        typer.Option("--pull-only", help="Only pull, don't push (default)"),
    ] = True,
) -> None:
    """Sync all managed repositories by pulling from remote.

    This pulls changes without creating commits. Use for keeping local repos
    up to date with remote. Will not sync repos with uncommitted changes.

    Examples:
        st git sync
        st --compact git sync
    """
    results: list[dict[str, Any]] = []

    for repo_path in _get_managed_repos():
        repo_status = _get_repo_status(repo_path)
        if not repo_status:
            continue

        result: dict[str, Any] = {
            "path": str(repo_path),
            "name": repo_path.name,
            "branch": repo_status.get("branch", "unknown"),
        }

        # Skip dirty repos
        if repo_status.get("uncommitted", 0) > 0:
            result["status"] = "skipped"
            result["reason"] = "uncommitted changes"
            results.append(result)
            continue

        # Pull from remote
        git_result = _run_git(["pull", "--ff-only"], repo_path)

        if git_result.returncode == 0:
            if "Already up to date" in git_result.stdout:
                result["status"] = "up_to_date"
            else:
                result["status"] = "updated"
                result["output"] = git_result.stdout.strip()
        else:
            result["status"] = "failed"
            result["error"] = git_result.stderr.strip()

        results.append(result)

    if is_compact():
        success = sum(1 for r in results if r["status"] in ("up_to_date", "updated"))
        failed = sum(1 for r in results if r["status"] == "failed")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        print(f"SYNC[{len(results)}] success:{success} failed:{failed} skipped:{skipped}")
        for r in results:
            status_str = r["status"][:10].ljust(10)
            name = r["name"][:15].ljust(15)
            reason = r.get("reason", r.get("error", ""))[:30]
            print(f"{name} {status_str} {reason}")
    else:
        output_json({"results": results, "total": len(results)})


@app.command()
def cleanup(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be removed without removing"),
    ] = False,
    max_age_days: Annotated[
        int,
        typer.Option("--max-age", "-d", help="Maximum age in days before cleanup"),
    ] = 30,
) -> None:
    """Remove stale git worktrees.

    Worktrees older than --max-age days (default 30) are removed.
    Use --dry-run to preview what would be removed.

    Examples:
        st git cleanup --dry-run
        st git cleanup --max-age 14
        st --compact git cleanup
    """
    from app.services.worktree_manager import WorktreeManager

    config = get_config()
    project_root = Path(config.project_root) if config.project_root else Path.cwd()

    try:
        manager = WorktreeManager(project_root)
        result = manager.cleanup_stale_worktrees(max_age_days=max_age_days, dry_run=dry_run)
    except Exception as e:
        output_error(f"Cleanup failed: {e}")
        raise typer.Exit(1) from None

    removed = result.get("removed", [])
    would_remove = result.get("would_remove", [])
    items = would_remove if dry_run else removed
    key = "would_remove" if dry_run else "removed"

    if is_compact():
        if dry_run:
            print(f"CLEANUP_DRY_RUN[{len(items)}]")
        else:
            print(f"CLEANUP[{len(items)}]")

        for item in items:
            task_id = item.get("task_id", "?")[:20].ljust(20)
            age = item.get("age_days", 0)
            print(f"{task_id} age:{age:.0f}d")

        if not items:
            print("No stale worktrees found")
    else:
        output_json({key: items, "max_age_days": max_age_days, "dry_run": dry_run})


@app.command()
def worktrees(
    project_id: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Filter by project ID"),
    ] = None,
) -> None:
    """List all active worktrees.

    Shows worktrees with their task IDs, branches, and change statistics.

    Examples:
        st git worktrees
        st git worktrees --project summitflow
        st --compact git worktrees
    """
    from app.services.worktree_manager import WorktreeManager

    config = get_config()
    project_root = Path(config.project_root) if config.project_root else Path.cwd()

    try:
        manager = WorktreeManager(project_root)
        worktrees_list = manager.list_active_worktrees(project_id=project_id)
    except Exception as e:
        output_error(f"Failed to list worktrees: {e}")
        raise typer.Exit(1) from None

    if is_compact():
        print(f"WORKTREES[{len(worktrees_list)}]")
        for wt in worktrees_list:
            task_id = wt.task_id[:20].ljust(20)
            branch = wt.branch[:20].ljust(20)
            commits = wt.commit_count
            files = wt.files_changed
            print(f"{task_id} {branch} commits:{commits} files:{files}")
    else:
        # Convert WorktreeInfo objects to dicts for JSON output
        wt_dicts = [
            {
                "task_id": wt.task_id,
                "project_id": wt.project_id,
                "branch": wt.branch,
                "path": str(wt.path),
                "commit_count": wt.commit_count,
                "files_changed": wt.files_changed,
                "additions": wt.additions,
                "deletions": wt.deletions,
            }
            for wt in worktrees_list
        ]
        output_json({"worktrees": wt_dicts, "total": len(wt_dicts)})
