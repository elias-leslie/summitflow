"""Cleanup commands for st CLI.

Provides worktree cleanup and stale detection for orphaned worktrees.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from ..client import APIError, STClient
from ..lib.worktree import (
    WorktreeInfo,
    get_active_worktrees,
    remove_worktree,
)
from ..output import output_json, output_success, output_warning

app = typer.Typer(help="Cleanup commands for stale resources")


class CleanupAction(StrEnum):
    """Recommended action for a stale worktree."""

    SAFE_DELETE = "safe_delete"  # No commits ahead, safe to remove
    ALREADY_MERGED = "already_merged"  # Commits already in main
    NEEDS_MERGE = "needs_merge"  # Has commits not in main
    HAS_CONFLICTS = "has_conflicts"  # Would conflict with main
    MANUAL_REVIEW = "manual_review"  # Complex state, needs human review
    TASK_ACTIVE = "task_active"  # Task still running/pending


@dataclass
class WorktreeAnalysis:
    """Analysis result for a worktree."""

    worktree: WorktreeInfo
    task_status: str | None  # None if task not found
    task_title: str | None
    commits_ahead: int
    commits_behind: int
    has_conflicts: bool
    has_uncommitted: bool
    last_commit_age_days: int | None
    action: CleanupAction
    reason: str


def _run_git(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command."""
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _get_repo_root() -> Path | None:
    """Get the main repository root."""
    try:
        result = _run_git(["rev-parse", "--show-toplevel"])
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def _get_commits_ahead_behind(worktree_path: Path, base_branch: str = "main") -> tuple[int, int]:
    """Get number of commits ahead and behind base branch."""
    try:
        # Fetch to ensure we have latest refs
        _run_git(["fetch", "origin", base_branch], cwd=worktree_path, check=False)

        # Get commits ahead (in worktree but not in origin/base)
        result = _run_git(
            ["rev-list", "--count", f"origin/{base_branch}..HEAD"],
            cwd=worktree_path,
            check=False,
        )
        ahead = int(result.stdout.strip()) if result.returncode == 0 else 0

        # Get commits behind (in origin/base but not in worktree)
        result = _run_git(
            ["rev-list", "--count", f"HEAD..origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        behind = int(result.stdout.strip()) if result.returncode == 0 else 0

        return ahead, behind
    except (subprocess.CalledProcessError, ValueError):
        return 0, 0


def _has_merge_conflicts(worktree_path: Path, base_branch: str = "main") -> bool:
    """Check if merging base branch would cause conflicts."""
    try:
        # Use merge-tree to check for conflicts without actually merging
        # Get current HEAD
        head_result = _run_git(["rev-parse", "HEAD"], cwd=worktree_path, check=False)
        if head_result.returncode != 0:
            return False
        head = head_result.stdout.strip()

        # Get base branch ref
        base_result = _run_git(
            ["rev-parse", f"origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        if base_result.returncode != 0:
            return False
        base = base_result.stdout.strip()

        # Try merge-tree (available in git 2.38+)
        # Falls back to checking merge-base approach
        merge_base_result = _run_git(
            ["merge-base", head, base],
            cwd=worktree_path,
            check=False,
        )
        if merge_base_result.returncode != 0:
            return False
        merge_base = merge_base_result.stdout.strip()

        # If merge-base equals head, base is ahead - no conflicts
        if merge_base == head:
            return False

        # If merge-base equals base, we're ahead - check for file conflicts
        # by doing a dry-run merge
        result = _run_git(
            ["merge", "--no-commit", "--no-ff", f"origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        has_conflict = result.returncode != 0 and "CONFLICT" in result.stdout + result.stderr

        # Abort the merge
        _run_git(["merge", "--abort"], cwd=worktree_path, check=False)

        return has_conflict
    except subprocess.CalledProcessError:
        return False


def _has_uncommitted_changes(worktree_path: Path) -> bool:
    """Check if worktree has uncommitted changes."""
    try:
        result = _run_git(["status", "--porcelain"], cwd=worktree_path, check=False)
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def _get_last_commit_age_days(worktree_path: Path) -> int | None:
    """Get age of last commit in days."""
    try:
        result = _run_git(
            ["log", "-1", "--format=%ct"],
            cwd=worktree_path,
            check=False,
        )
        if result.returncode != 0:
            return None
        timestamp = int(result.stdout.strip())
        commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
        age = datetime.now(UTC) - commit_time
        return age.days
    except (subprocess.CalledProcessError, ValueError):
        return None


def _is_already_merged(worktree_path: Path, base_branch: str = "main") -> bool:
    """Check if worktree branch is already merged into base."""
    try:
        # Get current branch HEAD
        head_result = _run_git(["rev-parse", "HEAD"], cwd=worktree_path, check=False)
        if head_result.returncode != 0:
            return False
        head = head_result.stdout.strip()

        # Check if this commit is an ancestor of origin/base
        result = _run_git(
            ["merge-base", "--is-ancestor", head, f"origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False


def _get_task_info(client: STClient, task_id: str) -> tuple[str | None, str | None]:
    """Get task status and title. Returns (status, title) or (None, None) if not found."""
    try:
        task = client.get_task(task_id)
        return task.get("status"), task.get("title")
    except APIError:
        return None, None


def analyze_worktree(worktree: WorktreeInfo, client: STClient) -> WorktreeAnalysis:
    """Analyze a worktree and recommend cleanup action."""
    task_status, task_title = _get_task_info(client, worktree.task_id)

    # Get git state
    commits_ahead, commits_behind = _get_commits_ahead_behind(worktree.path, worktree.base_branch)
    has_uncommitted = _has_uncommitted_changes(worktree.path)
    has_conflicts = _has_merge_conflicts(worktree.path, worktree.base_branch)
    last_commit_age = _get_last_commit_age_days(worktree.path)
    is_merged = _is_already_merged(worktree.path, worktree.base_branch)

    # Determine action
    if task_status in ("running", "pending", "queue"):
        action = CleanupAction.TASK_ACTIVE
        reason = f"Task is {task_status}"
    elif has_uncommitted:
        action = CleanupAction.MANUAL_REVIEW
        reason = "Has uncommitted changes"
    elif has_conflicts:
        action = CleanupAction.HAS_CONFLICTS
        reason = "Would conflict with main"
    elif is_merged or commits_ahead == 0:
        action = CleanupAction.SAFE_DELETE if not is_merged else CleanupAction.ALREADY_MERGED
        reason = "Already merged" if is_merged else "No commits ahead of main"
    elif commits_ahead > 0:
        action = CleanupAction.NEEDS_MERGE
        reason = f"{commits_ahead} commit(s) not in main"
    else:
        action = CleanupAction.MANUAL_REVIEW
        reason = "Complex state"

    return WorktreeAnalysis(
        worktree=worktree,
        task_status=task_status,
        task_title=task_title,
        commits_ahead=commits_ahead,
        commits_behind=commits_behind,
        has_conflicts=has_conflicts,
        has_uncommitted=has_uncommitted,
        last_commit_age_days=last_commit_age,
        action=action,
        reason=reason,
    )


def format_analysis(analysis: WorktreeAnalysis) -> str:
    """Format analysis for display."""
    status_icon = {
        CleanupAction.SAFE_DELETE: "[SAFE]",
        CleanupAction.ALREADY_MERGED: "[MERGED]",
        CleanupAction.NEEDS_MERGE: "[NEEDS_MERGE]",
        CleanupAction.HAS_CONFLICTS: "[CONFLICT]",
        CleanupAction.MANUAL_REVIEW: "[REVIEW]",
        CleanupAction.TASK_ACTIVE: "[ACTIVE]",
    }.get(analysis.action, "[?]")

    task_info = f"task:{analysis.task_status or 'NOT_FOUND'}"
    title = analysis.task_title[:40] if analysis.task_title else "?"

    age_str = (
        f"{analysis.last_commit_age_days}d" if analysis.last_commit_age_days is not None else "?"
    )
    commits_str = f"+{analysis.commits_ahead}/-{analysis.commits_behind}"

    flags = []
    if analysis.has_uncommitted:
        flags.append("dirty")
    if analysis.has_conflicts:
        flags.append("conflicts")
    flags_str = ",".join(flags) if flags else "-"

    return (
        f"{status_icon} {analysis.worktree.task_id}|{task_info}|{commits_str}|"
        f"age:{age_str}|{flags_str}|{analysis.reason}|{title}"
    )


def cleanup_worktree(analysis: WorktreeAnalysis, force: bool = False) -> tuple[bool, str]:
    """Cleanup a worktree based on analysis.

    Returns (success, message).
    """
    task_id = analysis.worktree.task_id

    # Safety checks
    if not force:
        if analysis.action == CleanupAction.TASK_ACTIVE:
            return False, f"Skipped: task is {analysis.task_status}"
        if analysis.action == CleanupAction.NEEDS_MERGE:
            return False, f"Skipped: has {analysis.commits_ahead} unmerged commit(s)"
        if analysis.action == CleanupAction.HAS_CONFLICTS:
            return False, "Skipped: would conflict with main"
        if analysis.action == CleanupAction.MANUAL_REVIEW:
            return False, f"Skipped: {analysis.reason}"

    # Remove the worktree
    try:
        project_id = analysis.worktree.project_id
        success = remove_worktree(task_id, delete_branch=True, project_id=project_id)
        if success:
            return True, "Removed"
        else:
            return False, "Worktree not found"
    except Exception as e:
        return False, f"Error: {e}"


@app.command("worktrees")
def cleanup_worktrees(
    auto: Annotated[
        bool,
        typer.Option("--auto", help="Auto-cleanup safe cases (merged, no commits ahead)"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Force cleanup all worktrees (with confirmation)"),
    ] = False,
    stale_days: Annotated[
        int,
        typer.Option("--stale-days", help="Consider worktrees stale after N days"),
    ] = 7,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be cleaned up without doing it"),
    ] = False,
) -> None:
    """List orphaned/stale worktrees with cleanup recommendations.

    Analyzes worktrees at ~/.local/share/st/worktrees/ and recommends actions:
    - SAFE: No commits ahead, can be safely deleted
    - MERGED: Already merged into main
    - NEEDS_MERGE: Has commits not in main
    - CONFLICT: Would conflict with main
    - REVIEW: Needs manual review (uncommitted changes, complex state)
    - ACTIVE: Task is still running/pending

    Examples:
        st cleanup worktrees                    # List with recommendations
        st cleanup worktrees --auto             # Auto-cleanup safe cases
        st cleanup worktrees --force            # Cleanup all (with warning)
        st cleanup worktrees --stale-days 14   # Mark stale after 14 days
        st cleanup worktrees --dry-run          # Preview cleanup
    """
    # Get all worktrees
    worktrees = get_active_worktrees()

    if not worktrees:
        output_success("No worktrees found")
        return

    typer.echo(f"Analyzing {len(worktrees)} worktree(s)...")

    # Analyze each worktree
    client = STClient(require_project=False)
    analyses: list[WorktreeAnalysis] = []

    for wt in worktrees:
        analysis = analyze_worktree(wt, client)
        analyses.append(analysis)

    # Categorize
    safe_to_delete = [
        a for a in analyses if a.action in (CleanupAction.SAFE_DELETE, CleanupAction.ALREADY_MERGED)
    ]
    needs_merge = [a for a in analyses if a.action == CleanupAction.NEEDS_MERGE]
    has_conflicts = [a for a in analyses if a.action == CleanupAction.HAS_CONFLICTS]
    needs_review = [a for a in analyses if a.action == CleanupAction.MANUAL_REVIEW]
    active_tasks = [a for a in analyses if a.action == CleanupAction.TASK_ACTIVE]

    # Mark stale based on age
    stale = [
        a
        for a in analyses
        if a.last_commit_age_days is not None and a.last_commit_age_days >= stale_days
    ]

    # Print summary
    typer.echo("")
    typer.echo(f"WORKTREE ANALYSIS [{len(worktrees)} total]")
    typer.echo(f"  Safe to delete: {len(safe_to_delete)}")
    typer.echo(f"  Needs merge:    {len(needs_merge)}")
    typer.echo(f"  Has conflicts:  {len(has_conflicts)}")
    typer.echo(f"  Manual review:  {len(needs_review)}")
    typer.echo(f"  Active tasks:   {len(active_tasks)}")
    typer.echo(f"  Stale (>{stale_days}d):  {len(stale)}")
    typer.echo("")

    # Print details
    for analysis in analyses:
        typer.echo(format_analysis(analysis))

    # Handle cleanup modes
    if not auto and not force:
        typer.echo("")
        typer.echo("Use --auto to cleanup safe cases or --force for all")
        return

    # Confirm force mode
    if force and not dry_run:
        typer.echo("")
        output_warning(
            f"FORCE MODE: Will cleanup ALL {len(worktrees)} worktrees including "
            f"{len(needs_merge)} with unmerged commits!"
        )
        if not typer.confirm("Are you sure?", default=False):
            typer.echo("Aborted")
            return

    # Perform cleanup
    typer.echo("")
    if dry_run:
        typer.echo("DRY RUN - No changes will be made:")

    cleaned = 0
    skipped = 0
    errors = 0

    targets = analyses if force else safe_to_delete

    for analysis in targets:
        if dry_run:
            typer.echo(f"  Would cleanup: {analysis.worktree.task_id}")
            cleaned += 1
        else:
            success, message = cleanup_worktree(analysis, force=force)
            if success:
                typer.echo(f"  Cleaned: {analysis.worktree.task_id}")
                cleaned += 1
            elif "Skipped" in message:
                typer.echo(f"  {message}: {analysis.worktree.task_id}")
                skipped += 1
            else:
                typer.echo(f"  {message}: {analysis.worktree.task_id}")
                errors += 1

    # Summary
    typer.echo("")
    if dry_run:
        output_success(f"Would cleanup {cleaned} worktree(s)")
    else:
        output_success(f"Cleaned {cleaned}, skipped {skipped}, errors {errors}")


@app.command("status")
def cleanup_status() -> None:
    """Show summary of worktrees and their cleanup status.

    Quick overview without detailed analysis.
    """
    worktrees = get_active_worktrees()

    if not worktrees:
        output_json({"worktrees": [], "total": 0})
        return

    result = {
        "worktrees": [
            {
                "task_id": wt.task_id,
                "path": str(wt.path),
                "branch": wt.branch,
                "base_branch": wt.base_branch,
            }
            for wt in worktrees
        ],
        "total": len(worktrees),
    }

    output_json(result)
