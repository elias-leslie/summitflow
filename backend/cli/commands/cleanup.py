"""Cleanup commands for st CLI.

Provides worktree cleanup and stale detection for orphaned worktrees.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import STClient
from ..lib.worktree import get_active_worktrees
from ..output import output_json, output_success, output_warning
from .cleanup_analysis import (
    CleanupAction,
    WorktreeAnalysis,
    analyze_worktree,
    cleanup_worktree,
    format_analysis,
)

# Re-export for backward compatibility
__all__ = [
    "CleanupAction",
    "WorktreeAnalysis",
    "analyze_worktree",
    "app",
    "cleanup_status",
    "cleanup_worktree",
    "cleanup_worktrees",
    "format_analysis",
]

app = typer.Typer(help="Cleanup commands for stale resources")


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
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Scan all projects (default: current project only)"),
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
    # Get worktrees scoped to current project (unless --all)
    from ..config import get_config_optional
    project_id = None if all_projects else (get_config_optional().project_id or None)
    worktrees = get_active_worktrees(project_id)

    if not worktrees:
        output_success("No worktrees found")
        return

    typer.echo(f"Analyzing {len(worktrees)} worktree(s)...")

    # Analyze each worktree
    client = STClient(require_project=False)
    analyses = [analyze_worktree(wt, client) for wt in worktrees]

    # Categorize
    safe_to_delete = [a for a in analyses if a.action in (CleanupAction.SAFE_DELETE, CleanupAction.ALREADY_MERGED)]
    needs_merge = [a for a in analyses if a.action == CleanupAction.NEEDS_MERGE]
    has_conflicts = [a for a in analyses if a.action == CleanupAction.HAS_CONFLICTS]
    needs_review = [a for a in analyses if a.action == CleanupAction.MANUAL_REVIEW]
    active_tasks = [a for a in analyses if a.action == CleanupAction.TASK_ACTIVE]
    stale = [a for a in analyses if a.last_commit_age_days is not None and a.last_commit_age_days >= stale_days]

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
    typer.echo("DRY RUN - No changes will be made:" if dry_run else "")
    cleaned = skipped = errors = 0
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
    msg = f"Would cleanup {cleaned} worktree(s)" if dry_run else f"Cleaned {cleaned}, skipped {skipped}, errors {errors}"
    output_success(msg)


@app.command("status")
def cleanup_status(
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Show all projects (default: current project only)"),
    ] = False,
) -> None:
    """Show summary of worktrees and their cleanup status.

    Quick overview without detailed analysis.
    """
    from ..config import get_config_optional
    project_id = None if all_projects else (get_config_optional().project_id or None)
    worktrees = get_active_worktrees(project_id)

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
