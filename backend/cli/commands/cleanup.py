"""Cleanup commands for st CLI.

Provides worktree cleanup, orphan inspection, and minimal salvage recovery.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from app.storage import tasks as task_store
from app.utils._git_branches import (
    assess_orphan_task_branches,
    prune_closed_orphan_task_branches,
    prune_equivalent_orphan_task_branches,
    prune_prunable_task_branches,
    prune_worktree_registrations,
)
from app.utils._git_core import run_git
from app.utils.git_helpers import build_repo_workspace_summary

from ..client import STClient
from ..config import get_config_optional
from ..lib.checkpoint import get_stale_checkpoints
from ..lib.worktree import create_worktree, get_active_worktrees
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
from .cleanup_display import RepoEntry, format_cleanup_status_compact, print_git_residue_report
from .cleanup_git import has_uncommitted_changes
from .cleanup_handlers import (
    categorize_worktrees,
    execute_cleanup,
    print_cleanup_results,
    print_worktree_summary,
)
from .cleanup_paths import cleanup_paths_command
from .cleanup_salvage import validate_salvage_candidate

# Re-export for backward compatibility
__all__ = [
    "CleanupAction",
    "WorktreeAnalysis",
    "analyze_worktree",
    "app",
    "cleanup_path",
    "cleanup_status",
    "cleanup_worktree",
    "cleanup_worktrees",
    "format_analysis",
]

app = typer.Typer(help="Cleanup commands for stale resources")

_NO_CLEANUP_FLAG_MSG = "Use --auto to cleanup safe cases or --force for all"
_DRY_RUN_MSG = "DRY RUN - No changes will be made:"
_ABORTED_MSG = "Aborted"


@app.callback()
def cleanup_callback(ctx: typer.Context) -> None:
    """Initialize context when the cleanup sub-app is invoked directly."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def get_project_id(all_projects: bool) -> str | None:
    """Get project ID based on --all flag."""
    if all_projects:
        return None
    return get_config_optional().project_id or None


def _iter_target_repos(all_projects: bool) -> list[Path]:
    """Return managed repositories relevant to the cleanup status request."""
    repos = [repo for repo in _get_managed_repos() if not repo.name.startswith(".")]
    if all_projects:
        return repos
    project_id = get_project_id(False)
    if project_id:
        return [repo for repo in repos if repo.name == project_id]
    return repos[:1] if repos else []


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


def _build_repo_cleanup_entry(repo_path: Path) -> RepoEntry:
    """Build cleanup counters for one managed repository."""
    project_id = repo_path.name
    ws = build_repo_workspace_summary(repo_path)
    active_worktrees = get_active_worktrees(project_id)
    client = STClient(require_project=False)
    analyses = [analyze_worktree(wt, client) for wt in active_worktrees]
    dirty_worktrees = sum(1 for wt in active_worktrees if has_uncommitted_changes(wt.path))
    stale_checkpoints = len(get_stale_checkpoints(project_id))
    needs_merge_tasks, conflict_tasks, review_tasks = _categorize_analyses(analyses)
    needs_cleanup = any((
        dirty_worktrees, stale_checkpoints, ws.orphan_branches, ws.prunable_branches,
        needs_merge_tasks, conflict_tasks, review_tasks,
    ))
    return RepoEntry(
        project_id=project_id, path=str(repo_path),
        active_worktrees=ws.active_worktrees, dirty_worktrees=dirty_worktrees,
        stale_checkpoints=stale_checkpoints,
        orphan_task_branches=ws.orphan_branches, prunable_task_branches=ws.prunable_branches,
        worktree_task_ids=ws.worktree_task_ids, orphan_branch_names=ws.orphan_branch_names,
        prunable_branch_names=ws.prunable_branch_names, salvage_task_ids=ws.salvage_task_ids,
        review_orphan_task_ids=ws.review_orphan_task_ids,
        needs_merge_count=len(needs_merge_tasks), conflict_count=len(conflict_tasks),
        review_count=len(review_tasks), needs_merge_tasks=needs_merge_tasks[:3],
        conflict_tasks=conflict_tasks[:3], review_tasks=review_tasks[:3],
        needs_cleanup=needs_cleanup,
    )


def build_cleanup_status_payload(all_projects: bool) -> dict[str, Any]:
    """Build the canonical cross-repo cleanup summary payload."""
    project_id = get_project_id(all_projects)
    worktrees = get_active_worktrees(project_id)
    repositories = [_build_repo_cleanup_entry(p) for p in _iter_target_repos(all_projects)]
    summary: dict[str, int] = {
        "repos": len(repositories),
        "repos_needing_cleanup": sum(1 for r in repositories if r["needs_cleanup"]),
        "active_worktrees": sum(r["active_worktrees"] for r in repositories),
        "dirty_worktrees": sum(r["dirty_worktrees"] for r in repositories),
        "stale_checkpoints": sum(r["stale_checkpoints"] for r in repositories),
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


def _analyze_and_display(
    worktrees: list, client: STClient, stale_days: int
) -> tuple[list[WorktreeAnalysis], object]:
    """Analyze worktrees, print summary, and return (analyses, categorization)."""
    analyses = [analyze_worktree(wt, client) for wt in worktrees]
    categorization = categorize_worktrees(analyses, stale_days)
    print_worktree_summary(len(worktrees), categorization, stale_days)
    for analysis in analyses:
        typer.echo(format_analysis(analysis))
    return analyses, categorization


def _cleanup_safe_git_residue(repos: list[Path], dry_run: bool) -> tuple[int, int, int, int]:
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


def _get_branch_subject(repo_path: Path, branch_name: str) -> str | None:
    """Return the latest commit subject for a branch."""
    result = run_git(["log", "-1", "--format=%s", branch_name], repo_path)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _build_salvage_description(task_id: str, branch_name: str, repo_path: Path) -> str:
    """Build a compact description for a recovered orphan branch task."""
    subject = _get_branch_subject(repo_path, branch_name)
    detail = f"Latest commit: {subject}." if subject else "Latest commit subject unavailable."
    return (
        f"Recovered from orphan branch {branch_name} in {repo_path.name}. "
        f"{detail} Resume review, salvage, or discard from the restored lane."
    )


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
    from ..lib.confirm_token import format_preview, generate_token, validate_token

    project_id = get_project_id(all_projects)
    worktrees = get_active_worktrees(project_id)

    if not worktrees:
        counts = _cleanup_safe_git_residue(_iter_target_repos(all_projects), dry_run) if auto else (0, 0, 0, 0)
        if auto and dry_run:
            typer.echo(_DRY_RUN_MSG)
        output_success("No worktrees found")
        if auto:
            print_git_residue_report(*counts)
        return

    typer.echo(f"Analyzing {len(worktrees)} worktree(s)...")
    client = STClient(require_project=False)
    analyses, categorization = _analyze_and_display(worktrees, client, stale_days)

    if not auto and not force:
        typer.echo("")
        typer.echo(_NO_CLEANUP_FLAG_MSG)
        return

    # --auto cleans only safe cases, no confirmation needed
    if auto and not force:
        typer.echo("")
        if dry_run:
            typer.echo(_DRY_RUN_MSG)
        targets = categorization.safe_to_delete
        results = execute_cleanup(targets, force=False, dry_run=dry_run)
        print_cleanup_results(results, dry_run)
        counts = _cleanup_safe_git_residue(_iter_target_repos(all_projects), dry_run)
        if not dry_run:
            print_git_residue_report(*counts)
        return

    # --force requires two-pass confirmation
    command_key = f"cleanup-worktrees-{project_id or 'all'}"
    if confirm is None:
        lines = [
            f"FORCE CLEANUP will remove ALL {len(analyses)} worktrees:",
        ]
        for analysis in analyses:
            action = analysis.action.value if hasattr(analysis.action, "value") else str(analysis.action)
            lines.append(f"  {analysis.worktree.path} [{action}]")
        if categorization.needs_merge:
            lines.append(f"  WARNING: {len(categorization.needs_merge)} have unmerged commits")
        token = generate_token(command_key)
        scope = "--all" if all_projects else ""
        print(format_preview(f"st cleanup worktrees --force {scope}".strip(), lines, token))
        raise typer.Exit(0)

    if not validate_token(command_key, confirm):
        output_error(
            "Invalid or expired confirm token.\n"
            "  Run `st cleanup worktrees --force` to preview and get a new token."
        )
        raise typer.Exit(1)

    typer.echo("")
    if dry_run:
        typer.echo(_DRY_RUN_MSG)
    results = execute_cleanup(analyses, force=True, dry_run=dry_run)
    print_cleanup_results(results, dry_run)
    counts = _cleanup_safe_git_residue(_iter_target_repos(all_projects), dry_run)
    if not dry_run:
        print_git_residue_report(*counts)


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


def _find_orphan_match(repos: list[Path], task_id: str) -> tuple[Path, object] | None:
    """Search repos for orphan assessment matching task_id."""
    for repo_path in repos:
        for item in assess_orphan_task_branches(repo_path):
            if item.task_id == task_id:
                return (repo_path, item)
    return None


@app.command("salvage")
def salvage_orphan(
    task_id: Annotated[str, typer.Argument(help="Missing-task orphan branch to recover")],
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Search all managed projects instead of current project only"),
    ] = False,
) -> None:
    """Recover a missing-task orphan branch into a normal task lane."""
    match = _find_orphan_match(_iter_target_repos(all_projects), task_id)
    if match is None:
        output_error(
            f"No unresolved orphan branch found for {task_id}. "
            "Use `st cleanup inspect-orphans` to find salvage candidates."
        )
        raise typer.Exit(1)

    repo_path, item = match
    if not validate_salvage_candidate(item, task_id):
        raise typer.Exit(1)

    title = _get_branch_subject(repo_path, item.branch_name) or f"Recover orphan branch {task_id}"
    description = _build_salvage_description(task_id, item.branch_name, repo_path)
    created = task_store.create_task(
        project_id=repo_path.name, title=title, description=description,
        task_id=task_id, labels=["cleanup:salvaged"],
    )
    task_store.update_task(task_id, branch_name=item.branch_name)
    try:
        worktree = create_worktree(task_id, project_id=repo_path.name)
    except Exception as exc:
        task_store.delete_task(task_id)
        output_error(f"Recovered task record for {task_id}, but failed to create worktree: {exc}")
        raise typer.Exit(1) from exc

    output_success(f"Recovered orphan branch {item.branch_name} into task {created['id']}")
    typer.echo(f"  project: {repo_path.name}")
    typer.echo(f"  title: {title}")
    typer.echo(f"  worktree: {worktree.path}")
    if item.has_node_modules_artifact:
        typer.echo("  note: branch includes node_modules artifact changes; inspect before merge")


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
    import os

    from ..lib.checkpoint import get_stale_checkpoints, remove_snapshot
    from ..lib.confirm_token import format_preview, generate_token, validate_token
    from ..lib.quick_snapshots import (
        LaneInspection,
        OrphanedSnapshotDir,
        SnapshotError,
        delete_lane,
        delete_orphaned_snapshots,
        find_orphaned_snapshot_dirs,
        inspect_lane,
    )
    from ..lib.worktree_paths import get_lanes_base_dir, workspaces_root_available

    if not workspaces_root_available():
        output_error("Btrfs workspaces not available — nothing to clean up.")
        raise typer.Exit(1)

    project_id = get_project_id(all_projects)
    if not project_id and not all_projects:
        output_error("Could not determine project. Use --all or run from a project directory.")
        raise typer.Exit(1)

    # Collect project IDs to scan
    from ..lib.worktree_paths import get_workspaces_root

    if all_projects:
        lanes_root = get_workspaces_root() / "lanes"
        project_ids = sorted(d.name for d in lanes_root.iterdir() if d.is_dir()) if lanes_root.is_dir() else []
    else:
        project_ids = [project_id]

    # Enumerate and inspect lanes
    all_inspections: list[LaneInspection] = []
    for pid in project_ids:
        lanes_base = get_lanes_base_dir(pid)
        if not lanes_base.is_dir():
            continue
        lane_dirs = [lane_name] if lane_name else sorted(d.name for d in lanes_base.iterdir() if d.is_dir())
        for name in lane_dirs:
            try:
                all_inspections.append(inspect_lane(pid, name))
            except SnapshotError:
                continue

    inspections = (
        all_inspections
        if lane_name
        else [inspection for inspection in all_inspections if not inspection.is_git_worktree]
    )

    # Also find orphaned snapshot directories (lane deleted but snapshots remain)
    orphaned_snap_dirs: list[OrphanedSnapshotDir] = []
    if not lane_name:  # Only scan for orphans when not targeting a specific lane
        for pid in project_ids:
            orphaned_snap_dirs.extend(find_orphaned_snapshot_dirs(pid))

    stale_checkpoints = []
    for pid in project_ids:
        for checkpoint in get_stale_checkpoints(pid):
            checkpoint_lane = Path(checkpoint.worktree_path).name if checkpoint.worktree_path else None
            if lane_name and checkpoint.task_id != lane_name and checkpoint_lane != lane_name:
                continue
            stale_checkpoints.append(checkpoint)

    if not inspections and not orphaned_snap_dirs and not stale_checkpoints:
        if lane_name:
            output_success("No matching lane, orphaned snapshots, or stale checkpoints found to clean up.")
        else:
            output_success("No orphaned lanes, orphaned snapshots, or stale checkpoints found to clean up.")
        return

    # Build command key for confirm token
    scope_label = "all" if all_projects else project_ids[0]
    target_label = lane_name or "all-lanes"
    command_key = f"cleanup-lanes-{scope_label}-{target_label}"

    if confirm is None:
        # First pass: preview
        lines: list[str] = []
        for insp in inspections:
            wt_label = "git-worktree" if insp.is_git_worktree else "orphan"
            lines.append(f"LANE {insp.project_id}/{insp.lane_name} [{wt_label}]")
            lines.append(f"  subvolume: {insp.lane_path}")
            if insp.branch:
                lines.append(f"  branch:   {insp.branch}")
            if insp.snapshot_paths:
                lines.append(f"  snapshots: {len(insp.snapshot_paths)}")
                for sp in insp.snapshot_paths:
                    lines.append(f"    {sp.name}")
            else:
                lines.append("  snapshots: 0")
            if insp.manifest_dir:
                lines.append(f"  manifest:  {insp.manifest_dir}")

        for orphan in orphaned_snap_dirs:
            lines.append(f"ORPHAN-SNAPSHOTS {orphan.project_id}/{orphan.lane_name} [lane-deleted]")
            lines.append(f"  snapshot-dir: {orphan.snapshot_dir}")
            lines.append(f"  snapshots: {len(orphan.snapshot_paths)}")
            for sp in orphan.snapshot_paths:
                lines.append(f"    {sp.name}")
            if orphan.manifest_dir:
                lines.append(f"  manifest:  {orphan.manifest_dir}")

        for checkpoint in stale_checkpoints:
            lines.append(f"STALE-CHECKPOINT {checkpoint.project_id}/{checkpoint.task_id}")
            lines.append(f"  worktree: {checkpoint.worktree_path or '-'}")
            lines.append(f"  created:  {checkpoint.created_at}")

        total_subvols = (
            sum(insp.total_items for insp in inspections)
            + sum(o.total_items for o in orphaned_snap_dirs)
        )
        total_targets = len(inspections) + len(orphaned_snap_dirs) + len(stale_checkpoints)
        summary = "DELETE explicit lane target(s)" if lane_name else "DELETE orphaned target(s)"
        lines.insert(0, f"{summary}: {total_targets} target(s), {total_subvols} subvolume(s):")
        lines.insert(1, "")

        token = generate_token(command_key)
        cmd_parts = ["st cleanup lanes"]
        if lane_name:
            cmd_parts.append(lane_name)
        if all_projects:
            cmd_parts.append("--all")
        print(format_preview(" ".join(cmd_parts), lines, token))
        if dry_run:
            typer.echo("  (dry-run: no token needed)")
        raise typer.Exit(0)

    # Second pass: validate and execute
    if not validate_token(command_key, confirm):
        output_error(
            "Invalid or expired confirm token.\n"
            "  Run the command without --confirm to preview and get a new token."
        )
        raise typer.Exit(1)

    if dry_run:
        typer.echo("DRY RUN — would delete:")
        for insp in inspections:
            typer.echo(f"  {insp.project_id}/{insp.lane_name} ({insp.total_items} subvolumes)")
        for orphan in orphaned_snap_dirs:
            typer.echo(f"  {orphan.project_id}/{orphan.lane_name} orphaned snapshots ({orphan.total_items})")
        for checkpoint in stale_checkpoints:
            typer.echo(f"  {checkpoint.project_id}/{checkpoint.task_id} stale checkpoint metadata")
        return

    # Ensure we're not inside a lane we're about to delete
    cwd = Path.cwd()
    for insp in inspections:
        try:
            cwd.relative_to(insp.lane_path)
            os.chdir(Path.home())
            break
        except ValueError:
            pass

    deleted = 0
    errors: list[str] = []
    for insp in inspections:
        try:
            delete_lane(insp)
            typer.echo(f"  Deleted lane: {insp.project_id}/{insp.lane_name}")
            deleted += 1
        except Exception as exc:
            errors.append(f"{insp.project_id}/{insp.lane_name}: {exc}")

    for orphan in orphaned_snap_dirs:
        try:
            delete_orphaned_snapshots(orphan)
            typer.echo(f"  Deleted orphaned snapshots: {orphan.project_id}/{orphan.lane_name}")
            deleted += 1
        except Exception as exc:
            errors.append(f"orphan:{orphan.project_id}/{orphan.lane_name}: {exc}")

    for checkpoint in stale_checkpoints:
        try:
            remove_snapshot(
                checkpoint.task_id,
                remove_worktree=False,
                project_id=checkpoint.project_id,
            )
            typer.echo(f"  Deleted stale checkpoint: {checkpoint.project_id}/{checkpoint.task_id}")
            deleted += 1
        except Exception as exc:
            errors.append(f"checkpoint:{checkpoint.project_id}/{checkpoint.task_id}: {exc}")

    output_success(f"Deleted {deleted} target(s), {len(errors)} error(s)")
    for err in errors:
        typer.echo(f"  ERROR {err}", err=True)


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
