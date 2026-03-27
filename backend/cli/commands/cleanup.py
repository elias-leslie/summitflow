"""Cleanup commands for st CLI.

Provides worktree cleanup, orphan inspection, and minimal salvage recovery.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from app.utils._git_branches import assess_orphan_task_branches
from app.utils.git_helpers import build_repo_workspace_summary

from ..config import get_config_optional
from ..lib.checkpoint import get_stale_checkpoints
from ..lib.confirm_token import confirm_gate, format_preview, generate_token
from ..lib.quick_snapshots import find_snapshot_residue
from ..lib.worktree import get_active_worktrees
from ..lib.worktree_paths import workspaces_root_available
from ..output import output_error, output_json, output_success
from ..output_context import OutputContext
from ._git_helpers import _get_managed_repos
from .cleanup_analysis import (
    CleanupAction,
    WorktreeAnalysis,
    analyze_worktree,
    cleanup_worktree,
    format_analysis,
)
from .cleanup_btrfs import (
    build_lane_preview_lines,
    collect_lane_targets,
    exit_if_empty,
    resolve_lanes_project_ids,
    run_lane_deletions,
    run_snapshot_deletions,
)
from .cleanup_display import RepoEntry, format_cleanup_status_compact, print_git_residue_report
from .cleanup_git import has_uncommitted_changes
from .cleanup_handlers import (
    analyze_and_display,
    build_force_worktree_preview,
    cleanup_safe_git_residue,
    run_worktree_cleanup,
)
from .cleanup_paths import cleanup_paths_command
from .cleanup_salvage import recover_orphan_task, validate_salvage_candidate

# Re-export for backward compatibility
__all__ = [
    "CleanupAction",
    "WorktreeAnalysis",
    "analyze_worktree",
    "app",
    "build_cleanup_status_payload",
    "cleanup_path",
    "cleanup_status",
    "cleanup_worktree",
    "cleanup_worktrees",
    "format_analysis",
]

app = typer.Typer(help="Cleanup commands for stale resources")

_NO_CLEANUP_FLAG_MSG = "Use --auto to cleanup safe cases or --force for all"
_DRY_RUN_MSG = "DRY RUN - No changes will be made:"


@app.callback()
def cleanup_callback(ctx: typer.Context) -> None:
    """Initialize context when the cleanup sub-app is invoked directly."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def get_project_id(all_projects: bool, project_id_override: str | None = None) -> str | None:
    """Get project ID based on --all flag."""
    if all_projects:
        return None
    if project_id_override:
        return project_id_override
    return get_config_optional().project_id or None


def _iter_target_repos(all_projects: bool, project_id_override: str | None = None) -> list[Path]:
    """Return managed repositories relevant to the cleanup status request."""
    repos = [repo for repo in _get_managed_repos() if not repo.name.startswith(".")]
    if all_projects:
        return repos
    project_id = get_project_id(False, project_id_override)
    if project_id:
        return [repo for repo in repos if repo.name == project_id]
    return repos[:1] if repos else []


def _iter_target_project_ids(all_projects: bool, project_id_override: str | None = None) -> list[str]:
    """Return managed project IDs relevant to the cleanup request."""
    return [repo.name for repo in _iter_target_repos(all_projects, project_id_override)]


def _categorize_analyses(analyses: list[WorktreeAnalysis]) -> tuple[list[str], list[str], list[str]]:
    """Return (needs_merge_tasks, conflict_tasks, review_tasks) from analyses."""
    needs_merge = [
        a.worktree.task_id for a in analyses
        if a.action == CleanupAction.NEEDS_MERGE and a.task_status is not None
    ]
    conflicts = [a.worktree.task_id for a in analyses if a.action == CleanupAction.HAS_CONFLICTS]
    review = [
        a.worktree.task_id for a in analyses
        if a.action == CleanupAction.MANUAL_REVIEW
        or (a.action == CleanupAction.NEEDS_MERGE and a.task_status is None)
    ]
    return needs_merge, conflicts, review


def _existing_worktrees(worktrees: list) -> list:
    """Filter out worktrees whose paths disappeared mid-cleanup."""
    return [wt for wt in worktrees if Path(wt.path).exists()]


def _build_repo_cleanup_entry(repo_path: Path) -> RepoEntry:
    """Build cleanup counters for one managed repository."""
    project_id = repo_path.name
    ws = build_repo_workspace_summary(repo_path)
    active_worktrees = _existing_worktrees(get_active_worktrees(project_id))
    analyses = [analyze_worktree(wt) for wt in active_worktrees]
    dirty_worktrees = sum(1 for wt in active_worktrees if has_uncommitted_changes(wt.path))
    dirty_main_repo = bool(getattr(ws, "dirty_main_repo", False))
    stale_checkpoints = len(get_stale_checkpoints(project_id))
    snapshot_residue = len(find_snapshot_residue([project_id], project_id=project_id))
    needs_merge_tasks, conflict_tasks, review_tasks = _categorize_analyses(analyses)
    needs_cleanup = any((
        dirty_main_repo, dirty_worktrees, stale_checkpoints, snapshot_residue, ws.orphan_branches, ws.prunable_branches,
        needs_merge_tasks, conflict_tasks, review_tasks,
    ))
    return RepoEntry(
        project_id=project_id, path=str(repo_path),
        active_worktrees=ws.active_worktrees, dirty_worktrees=dirty_worktrees,
        dirty_main_repo=dirty_main_repo,
        stale_checkpoints=stale_checkpoints, snapshot_residue=snapshot_residue,
        orphan_task_branches=ws.orphan_branches, prunable_task_branches=ws.prunable_branches,
        worktree_task_ids=ws.worktree_task_ids, orphan_branch_names=ws.orphan_branch_names,
        prunable_branch_names=ws.prunable_branch_names, salvage_task_ids=ws.salvage_task_ids,
        review_orphan_task_ids=ws.review_orphan_task_ids,
        needs_merge_count=len(needs_merge_tasks), conflict_count=len(conflict_tasks),
        review_count=len(review_tasks), needs_merge_tasks=needs_merge_tasks[:3],
        conflict_tasks=conflict_tasks[:3], review_tasks=review_tasks[:3],
        needs_cleanup=needs_cleanup,
    )


def build_cleanup_status_payload(
    all_projects: bool,
    *,
    project_id_override: str | None = None,
) -> dict[str, Any]:
    """Build the canonical cross-repo cleanup summary payload."""
    project_id = get_project_id(all_projects, project_id_override)
    worktrees = _existing_worktrees(get_active_worktrees(project_id))
    repositories = [
        _build_repo_cleanup_entry(p)
        for p in _iter_target_repos(all_projects, project_id_override)
    ]
    summary: dict[str, int] = {
        "repos": len(repositories),
        "repos_needing_cleanup": sum(1 for r in repositories if r["needs_cleanup"]),
        "active_worktrees": sum(r["active_worktrees"] for r in repositories),
        "dirty_worktrees": sum(
            int(r["dirty_worktrees"]) + int(bool(r.get("dirty_main_repo")))
            for r in repositories
        ),
        "stale_checkpoints": sum(r["stale_checkpoints"] for r in repositories),
        "snapshot_residue": sum(r["snapshot_residue"] for r in repositories),
        "orphan_task_branches": sum(r["orphan_task_branches"] for r in repositories),
        "prunable_task_branches": sum(r["prunable_task_branches"] for r in repositories),
    }
    return {
        "summary": summary,
        "repositories": repositories,
        "worktrees": [
            {"task_id": wt.task_id, "path": str(wt.path), "branch": wt.branch,
             "base_branch": wt.base_branch, "project_id": wt.project_id}
            for wt in worktrees
        ],
        "total": len(worktrees),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("worktrees")
def cleanup_worktrees(
    auto: Annotated[bool, typer.Option("--auto", help="Auto-cleanup safe cases (merged, no commits ahead)")] = False,
    force: Annotated[bool, typer.Option("--force", help="Force cleanup all worktrees")] = False,
    stale_days: Annotated[int, typer.Option("--stale-days", help="Consider worktrees stale after N days")] = 7,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be cleaned up without doing it")] = False,
    all_projects: Annotated[bool, typer.Option("--all", help="Scan all projects (default: current project only)")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """List orphaned/stale worktrees with recommendations. Actions: SAFE, MERGED, NEEDS_MERGE, CONFLICT, REVIEW, ACTIVE."""
    project_id = get_project_id(all_projects)
    worktrees = get_active_worktrees(project_id)

    if not worktrees:
        counts = cleanup_safe_git_residue(_iter_target_repos(all_projects), dry_run) if auto else (0, 0, 0, 0)
        if auto and dry_run:
            typer.echo(_DRY_RUN_MSG)
        output_success("No worktrees found")
        if auto:
            print_git_residue_report(*counts)
        return

    typer.echo(f"Analyzing {len(worktrees)} worktree(s)...")
    analyses, categorization = analyze_and_display(worktrees, stale_days)

    if not auto and not force:
        typer.echo("")
        typer.echo(_NO_CLEANUP_FLAG_MSG)
        return

    repos = _iter_target_repos(all_projects)

    if auto and not force:
        typer.echo("")
        if dry_run:
            typer.echo(_DRY_RUN_MSG)
        run_worktree_cleanup(categorization.safe_to_delete, force=False, dry_run=dry_run, repos=repos)
        return

    # --force requires two-pass confirmation
    command_key, preview_lines, cmd = build_force_worktree_preview(analyses, categorization, project_id, all_projects)
    confirm_gate(command_key, confirm, preview_lines, cmd)

    typer.echo("")
    if dry_run:
        typer.echo(_DRY_RUN_MSG)
    run_worktree_cleanup(analyses, force=True, dry_run=dry_run, repos=repos)


@app.command("inspect-orphans")
def inspect_orphans(
    all_projects: Annotated[bool, typer.Option("--all", help="Inspect all managed projects")] = False,
) -> None:
    """Inspect unresolved orphan task branches that need salvage or review."""
    lines: list[str] = []
    salvage_count = review_count = 0
    for repo_path in _iter_target_repos(all_projects):
        for item in assess_orphan_task_branches(repo_path):
            if item.resolution == "salvage":
                salvage_count += 1
            else:
                review_count += 1
            flags = []
            if item.task_status is None:
                flags.append("task_missing")
            if item.has_node_modules_artifact:
                flags.append("node_modules_artifact")
            lines.append(
                f"{repo_path.name} {item.task_id} branch:{item.branch_name} "
                f"resolution:{item.resolution} task:{item.task_status or 'missing'} "
                f"ahead:{item.commits_ahead} files:{item.files_changed} "
                f"flags:{','.join(flags) if flags else '-'}"
            )
    scope = "all" if all_projects else "current"
    typer.echo(f"ORPHAN-REVIEW[{scope}]:total={len(lines)} salvage={salvage_count} review={review_count}")
    for line in lines:
        typer.echo(line)


@app.command("salvage")
def salvage_orphan(
    task_id: Annotated[str, typer.Argument(help="Missing-task orphan branch to recover")],
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Search all managed projects instead of current project only"),
    ] = False,
) -> None:
    """Recover a missing-task orphan branch into a normal task lane."""
    repos = _iter_target_repos(all_projects)
    match = next(
        ((repo, item) for repo in repos for item in assess_orphan_task_branches(repo) if item.task_id == task_id),
        None,
    )
    if match is None:
        output_error(
            f"No unresolved orphan branch found for {task_id}. "
            "Use `st cleanup inspect-orphans` to find salvage candidates."
        )
        raise typer.Exit(1)

    repo_path, item = match
    if not validate_salvage_candidate(item, task_id):
        raise typer.Exit(1)
    recover_orphan_task(repo_path, item, task_id)


@app.command("lanes")
def cleanup_lanes(
    lane_name: Annotated[str | None, typer.Argument(help="Specific lane name to delete (omit to scan all)")] = None,
    all_projects: Annotated[bool, typer.Option("--all", help="Scan all projects (default: current project only)")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be deleted without deleting it")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Delete orphaned Btrfs lanes and their snapshots.

    Without a lane name, this targets only orphaned/unmanaged lanes plus
    orphaned snapshot directories. With an explicit lane name, it will delete
    that exact lane even if it is still a registered git worktree.

    Uses two-pass confirmation: first run shows blast radius, second run with
    --confirm TOKEN executes.
    """
    if not workspaces_root_available():
        output_error("Btrfs workspaces not available — nothing to clean up.")
        raise typer.Exit(1)

    project_id = get_project_id(all_projects)
    if not project_id and not all_projects:
        output_error("Could not determine project. Use --all or run from a project directory.")
        raise typer.Exit(1)

    project_ids = resolve_lanes_project_ids(all_projects, project_id)
    inspections, orphaned_snap_dirs, stale_checkpoints = collect_lane_targets(project_ids, lane_name)

    exit_if_empty(
        not inspections and not orphaned_snap_dirs and not stale_checkpoints,
        lane_name,
        "No matching lane, orphaned snapshots, or stale checkpoints found to clean up.",
        "No orphaned lanes, orphaned snapshots, or stale checkpoints found to clean up.",
    )

    scope_label = "all" if all_projects else project_ids[0]
    command_key = f"cleanup-lanes-{scope_label}-{lane_name or 'all-lanes'}"
    preview_lines = build_lane_preview_lines(inspections, orphaned_snap_dirs, stale_checkpoints, lane_name)
    cmd = " ".join(["st cleanup lanes"] + ([lane_name] if lane_name else []) + (["--all"] if all_projects else []))

    if confirm is None and dry_run:
        token = generate_token(command_key)
        print(format_preview(cmd, preview_lines, token))
        typer.echo("  (dry-run: no token needed)")
        raise typer.Exit(0)

    confirm_gate(command_key, confirm, preview_lines, cmd)
    run_lane_deletions(inspections, orphaned_snap_dirs, stale_checkpoints, dry_run)


@app.command("snapshots")
def cleanup_snapshots(
    residue_name: Annotated[str | None, typer.Argument(help="Specific legacy snapshot residue to delete")] = None,
    all_projects: Annotated[bool, typer.Option("--all", help="Scan all projects (default: current project only)")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be deleted without deleting it")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Delete legacy snapshot residue outside the current managed lane/project layout."""
    if not workspaces_root_available():
        output_error("Btrfs workspaces not available — nothing to clean up.")
        raise typer.Exit(1)

    project_ids = _iter_target_project_ids(all_projects)
    current_project_id = get_project_id(all_projects)
    residues = find_snapshot_residue(project_ids, project_id=current_project_id)
    if residue_name:
        residues = [r for r in residues if r.residue_name == residue_name]

    exit_if_empty(
        not residues,
        residue_name,
        "No matching snapshot residue found to clean up.",
        "No legacy snapshot residue found to clean up.",
    )

    scope_label = "all" if all_projects else (current_project_id or "unknown")
    command_key = f"cleanup-snapshots-{scope_label}-{residue_name or 'all-snapshots'}"
    preview_lines = [f"DELETE legacy snapshot residue: {len(residues)} target(s):", ""]
    for residue in residues:
        owner = residue.project_id or "unowned"
        preview_lines.append(f"SNAPSHOT-RESIDUE {owner}/{residue.residue_name} [{residue.residue_type}]")
        preview_lines.append(f"  path: {residue.path}")

    cmd = " ".join(["st cleanup snapshots"] + ([residue_name] if residue_name else []) + (["--all"] if all_projects else []))
    confirm_gate(command_key, confirm, preview_lines, cmd)
    run_snapshot_deletions(residues, dry_run)


@app.command("status")
def cleanup_status(
    ctx: typer.Context,
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Show all projects (default: current project only)"),
    ] = False,
    fail_on_residue: Annotated[
        bool,
        typer.Option("--fail-on-residue", help="Exit nonzero when any managed repo still needs cleanup"),
    ] = False,
) -> None:
    """Show summary of worktrees and their cleanup status."""
    result = build_cleanup_status_payload(all_projects)
    if ctx.obj.is_compact:
        format_cleanup_status_compact(result, all_projects)
    else:
        output_json(result)
    if fail_on_residue and result["summary"]["repos_needing_cleanup"] > 0:
        raise typer.Exit(2)


@app.command("path")
def cleanup_path(
    paths: Annotated[list[str], typer.Argument(help="Path(s) to remove (repo-relative or absolute)")],
    recursive: Annotated[bool, typer.Option("--recursive", help="Allow directory deletion")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be deleted without deleting it")] = False,
) -> None:
    """Safely remove paths with guardrails. Supports repo-local and non-repo paths under home."""
    cleanup_paths_command(paths, recursive=recursive, dry_run=dry_run)
