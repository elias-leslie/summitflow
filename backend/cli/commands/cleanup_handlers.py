"""Checkpoint cleanup orchestration and execution logic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from app.utils._git_branches import (
    prune_checkout_registrations,
    prune_closed_orphan_task_branches,
    prune_equivalent_orphan_task_branches,
    prune_prunable_task_branches,
)

from .cleanup_analysis import (
    CheckpointAnalysis,
    CleanupAction,
    analyze_checkpoint,
    cleanup_checkpoint,
    format_analysis,
)


@dataclass
class CheckpointCategorization:
    """Categorized checkpoint analyses."""

    safe_to_delete: list[CheckpointAnalysis]
    needs_merge: list[CheckpointAnalysis]
    has_conflicts: list[CheckpointAnalysis]
    needs_review: list[CheckpointAnalysis]
    active_tasks: list[CheckpointAnalysis]
    stale: list[CheckpointAnalysis]


def categorize_checkpoints(
    analyses: list[CheckpointAnalysis], stale_days: int
) -> CheckpointCategorization:
    """Categorize checkpoint analyses by cleanup action and staleness."""
    return CheckpointCategorization(
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


def print_checkpoint_summary(
    total: int, categorization: CheckpointCategorization, stale_days: int
) -> None:
    """Print summary of checkpoint analysis."""
    typer.echo("")
    typer.echo(f"CHECKPOINT ANALYSIS [{total} total]")
    typer.echo(f"  Safe to delete: {len(categorization.safe_to_delete)}")
    typer.echo(f"  Needs merge:    {len(categorization.needs_merge)}")
    typer.echo(f"  Has conflicts:  {len(categorization.has_conflicts)}")
    typer.echo(f"  Manual review:  {len(categorization.needs_review)}")
    typer.echo(f"  Active tasks:   {len(categorization.active_tasks)}")
    typer.echo(f"  Stale (>{stale_days}d):  {len(categorization.stale)}")
    typer.echo("")


def confirm_force_cleanup(checkpoint_count: int, unmerged_count: int) -> bool:
    """Check force cleanup conditions. Always returns True (CLI is non-interactive)."""
    from ..output import output_warning

    output_warning(
        f"FORCE MODE: Cleaning ALL {checkpoint_count} checkpoints including "
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
    targets: list[CheckpointAnalysis], force: bool, dry_run: bool
) -> CleanupResults:
    """Execute cleanup on target checkpoints.

    Args:
        targets: List of checkpoint analyses to clean up
        force: Whether to force cleanup of risky checkpoints
        dry_run: Whether to only simulate cleanup

    Returns:
        CleanupResults with counts of cleaned, skipped, and errored checkpoints
    """
    cleaned = skipped = errors = 0

    for analysis in targets:
        if dry_run:
            typer.echo(f"  Would cleanup: {analysis.checkpoint.task_id}")
            cleaned += 1
            continue

        success, message = cleanup_checkpoint(analysis, force=force)
        if success:
            typer.echo(f"  Cleaned: {analysis.checkpoint.task_id}")
            cleaned += 1
        elif "Skipped" in message:
            typer.echo(f"  {message}: {analysis.checkpoint.task_id}")
            skipped += 1
        else:
            typer.echo(f"  {message}: {analysis.checkpoint.task_id}")
            errors += 1

    return CleanupResults(cleaned=cleaned, skipped=skipped, errors=errors)


def print_cleanup_results(results: CleanupResults, dry_run: bool) -> None:
    """Print final cleanup results summary."""
    from ..output import output_success

    typer.echo("")
    if dry_run:
        message = f"Would cleanup {results.cleaned} checkpoint(s)"
    else:
        message = f"Cleaned {results.cleaned}, skipped {results.skipped}, errors {results.errors}"
    output_success(message)


def analyze_and_display(
    checkpoints: list, stale_days: int
) -> tuple[list[CheckpointAnalysis], CheckpointCategorization]:
    """Analyze checkpoints, print summary, and return (analyses, categorization)."""
    analyses = [analyze_checkpoint(checkpoint) for checkpoint in checkpoints]
    categorization = categorize_checkpoints(analyses, stale_days)
    print_checkpoint_summary(len(checkpoints), categorization, stale_days)
    for analysis in analyses:
        typer.echo(format_analysis(analysis))
    return analyses, categorization


def run_checkpoint_cleanup(targets, force: bool, dry_run: bool, repos: list[Path]) -> None:
    """Execute checkpoint cleanup and print results and git residue report."""
    from .cleanup_display import print_git_residue_report

    results = execute_cleanup(targets, force=force, dry_run=dry_run)
    print_cleanup_results(results, dry_run)
    counts = cleanup_safe_git_residue(repos, dry_run)
    if not dry_run:
        print_git_residue_report(*counts)


def build_force_checkpoint_preview(
    analyses: list,
    categorization: CheckpointCategorization,
    project_id: str | None,
    all_projects: bool,
) -> tuple[str, list[str], str]:
    """Build command_key, preview_lines, and cmd for --force checkpoint cleanup."""
    command_key = f"cleanup-checkpoints-{project_id or 'all'}"
    preview_lines = [f"FORCE CLEANUP will remove ALL {len(analyses)} checkpoints:"]
    for analysis in analyses:
        action = analysis.action.value if hasattr(analysis.action, "value") else str(analysis.action)
        preview_lines.append(
            f"  {analysis.checkpoint.project_id}:{analysis.checkpoint.branch} [{action}]"
        )
    if categorization.needs_merge:
        preview_lines.append(f"  WARNING: {len(categorization.needs_merge)} have unmerged commits")
    scope = "--all" if all_projects else ""
    return command_key, preview_lines, f"st cleanup checkpoints --force {scope}".strip()


def cleanup_safe_git_residue(repos: list[Path], dry_run: bool) -> tuple[int, int, int, int]:
    """Prune stale git admin registrations and safe orphan task branches."""
    if dry_run:
        return (0, 0, 0, 0)
    pruned_regs = pruned_branches = pruned_equiv = pruned_closed = 0
    for repo_path in repos:
        pruned_regs += prune_checkout_registrations(repo_path)
        pruned_branches += len(prune_prunable_task_branches(repo_path))
        pruned_equiv += len(prune_equivalent_orphan_task_branches(repo_path))
        pruned_closed += len(prune_closed_orphan_task_branches(repo_path))
    return pruned_regs, pruned_branches, pruned_equiv, pruned_closed
