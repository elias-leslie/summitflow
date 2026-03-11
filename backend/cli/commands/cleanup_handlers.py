"""Worktree cleanup orchestration and execution logic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from app.utils._git_branches import (
    prune_closed_orphan_task_branches,
    prune_equivalent_orphan_task_branches,
    prune_prunable_task_branches,
    prune_worktree_registrations,
)

from .cleanup_analysis import CleanupAction, WorktreeAnalysis, cleanup_worktree


@dataclass
class WorktreeCategorization:
    """Categorized worktree analyses."""

    safe_to_delete: list[WorktreeAnalysis]
    needs_merge: list[WorktreeAnalysis]
    has_conflicts: list[WorktreeAnalysis]
    needs_review: list[WorktreeAnalysis]
    active_tasks: list[WorktreeAnalysis]
    stale: list[WorktreeAnalysis]


def categorize_worktrees(
    analyses: list[WorktreeAnalysis], stale_days: int
) -> WorktreeCategorization:
    """Categorize worktree analyses by cleanup action and staleness."""
    return WorktreeCategorization(
        safe_to_delete=[
            a
            for a in analyses
            if a.action in (CleanupAction.SAFE_DELETE, CleanupAction.ALREADY_MERGED)
        ],
        needs_merge=[a for a in analyses if a.action == CleanupAction.NEEDS_MERGE],
        has_conflicts=[a for a in analyses if a.action == CleanupAction.HAS_CONFLICTS],
        needs_review=[a for a in analyses if a.action == CleanupAction.MANUAL_REVIEW],
        active_tasks=[a for a in analyses if a.action == CleanupAction.TASK_ACTIVE],
        stale=[
            a
            for a in analyses
            if a.last_commit_age_days is not None and a.last_commit_age_days >= stale_days
        ],
    )


def print_worktree_summary(
    total: int, categorization: WorktreeCategorization, stale_days: int
) -> None:
    """Print summary of worktree analysis."""
    typer.echo("")
    typer.echo(f"WORKTREE ANALYSIS [{total} total]")
    typer.echo(f"  Safe to delete: {len(categorization.safe_to_delete)}")
    typer.echo(f"  Needs merge:    {len(categorization.needs_merge)}")
    typer.echo(f"  Has conflicts:  {len(categorization.has_conflicts)}")
    typer.echo(f"  Manual review:  {len(categorization.needs_review)}")
    typer.echo(f"  Active tasks:   {len(categorization.active_tasks)}")
    typer.echo(f"  Stale (>{stale_days}d):  {len(categorization.stale)}")
    typer.echo("")


def confirm_force_cleanup(worktree_count: int, unmerged_count: int) -> bool:
    """Check force cleanup conditions. Always returns True (CLI is non-interactive)."""
    from ..output import output_warning

    output_warning(
        f"FORCE MODE: Cleaning ALL {worktree_count} worktrees including "
        f"{unmerged_count} with unmerged commits"
    )
    return True


@dataclass
class CleanupResults:
    """Results of cleanup execution."""

    cleaned: int
    skipped: int
    errors: int


def execute_cleanup(
    targets: list[WorktreeAnalysis], force: bool, dry_run: bool
) -> CleanupResults:
    """Execute cleanup on target worktrees.

    Args:
        targets: List of worktree analyses to clean up
        force: Whether to force cleanup of risky worktrees
        dry_run: Whether to only simulate cleanup

    Returns:
        CleanupResults with counts of cleaned, skipped, and errored worktrees
    """
    cleaned = skipped = errors = 0

    for analysis in targets:
        if dry_run:
            typer.echo(f"  Would cleanup: {analysis.worktree.task_id}")
            cleaned += 1
            continue

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

    return CleanupResults(cleaned=cleaned, skipped=skipped, errors=errors)


def print_cleanup_results(results: CleanupResults, dry_run: bool) -> None:
    """Print final cleanup results summary."""
    from ..output import output_success

    typer.echo("")
    if dry_run:
        message = f"Would cleanup {results.cleaned} worktree(s)"
    else:
        message = f"Cleaned {results.cleaned}, skipped {results.skipped}, errors {results.errors}"
    output_success(message)


def cleanup_safe_git_residue(repos: list[Path], dry_run: bool) -> tuple[int, int, int, int]:
    """Prune stale worktree registrations and safe orphan task branches."""
    if dry_run:
        return (0, 0, 0, 0)
    pruned_regs = pruned_branches = pruned_equiv = pruned_closed = 0
    for repo_path in repos:
        prune_worktree_registrations(repo_path)
        pruned_regs += 1
        pruned_branches += len(prune_prunable_task_branches(repo_path))
        pruned_equiv += len(prune_equivalent_orphan_task_branches(repo_path))
        pruned_closed += len(prune_closed_orphan_task_branches(repo_path))
    return pruned_regs, pruned_branches, pruned_equiv, pruned_closed
