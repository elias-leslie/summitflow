"""Cleanup commands for st CLI.

Provides worktree cleanup and stale detection for orphaned worktrees.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import STClient
from ..lib.worktree import get_active_worktrees
from ..output import output_json, output_success
from .cleanup_analysis import (
    CleanupAction,
    WorktreeAnalysis,
    analyze_worktree,
    cleanup_worktree,
    format_analysis,
)
from .cleanup_handlers import (
    categorize_worktrees,
    confirm_force_cleanup,
    execute_cleanup,
    print_cleanup_results,
    print_worktree_summary,
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


def get_project_id(all_projects: bool) -> str | None:
    """Get project ID based on --all flag."""
    if all_projects:
        return None
    from ..config import get_config_optional

    return get_config_optional().project_id or None


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
    project_id = get_project_id(all_projects)
    worktrees = get_active_worktrees(project_id)

    if not worktrees:
        output_success("No worktrees found")
        return

    typer.echo(f"Analyzing {len(worktrees)} worktree(s)...")

    # Analyze and categorize
    client = STClient(require_project=False)
    analyses = [analyze_worktree(wt, client) for wt in worktrees]
    categorization = categorize_worktrees(analyses, stale_days)

    # Print analysis
    print_worktree_summary(len(worktrees), categorization, stale_days)
    for analysis in analyses:
        typer.echo(format_analysis(analysis))

    # Check if cleanup is requested
    if not auto and not force:
        typer.echo("")
        typer.echo("Use --auto to cleanup safe cases or --force for all")
        return

    # Confirm force mode if needed
    if force and not dry_run and not confirm_force_cleanup(len(worktrees), len(categorization.needs_merge)):
        typer.echo("Aborted")
        return

    # Execute cleanup
    typer.echo("")
    if dry_run:
        typer.echo("DRY RUN - No changes will be made:")
    targets = analyses if force else categorization.safe_to_delete
    results = execute_cleanup(targets, force=force, dry_run=dry_run)
    print_cleanup_results(results, dry_run)


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
    project_id = get_project_id(all_projects)
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
