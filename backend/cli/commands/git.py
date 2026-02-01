"""Git management commands for the CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(help="Git repository management")


@app.callback()
def git_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _get_summitflow_api_url() -> str:
    """Get SummitFlow API URL for projects endpoint."""
    api_base = os.getenv("ST_API_BASE", "http://localhost:8001/api")
    return f"{api_base}/projects"


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
        response = httpx.get(_get_summitflow_api_url(), timeout=2.0)
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
    ctx: typer.Context,
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

    if ctx.obj.is_compact:
        print(f"GIT[{len(repos)}]")
        for repo in repos:
            print(_format_compact_repo(repo))
    else:
        output_json({"repositories": repos, "total": len(repos)})


@app.command()
def sync(
    ctx: typer.Context,
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

    if ctx.obj.is_compact:
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
