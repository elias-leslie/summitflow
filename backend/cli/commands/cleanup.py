"""Cleanup commands for st CLI.

Provides checkpoint cleanup, orphan inspection, and minimal salvage recovery.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from app.utils._git_branches import assess_orphan_task_branches
from app.utils.git_helpers import build_repo_workspace_summary

from ..lib import cleanroom_prune
from ..lib.checkpoint import get_active_checkpoints, get_stale_checkpoints, remove_snapshot
from ..lib.checkpoint_branches import resolve_task_branch
from ..lib.confirm_token import confirm_gate
from ..lib.quick_snapshots import SnapshotError, find_snapshot_residue
from ..output import output_error, output_json, output_success
from ..output_context import OutputContext
from .cleanup_analysis import (
    CheckpointAnalysis,
    CleanupAction,
    analyze_checkpoint,
    cleanup_checkpoint,
    format_analysis,
)
from .cleanup_display import format_cleanup_status_compact, print_git_residue_report
from .cleanup_handlers import (
    analyze_and_display,
    build_force_checkpoint_preview,
    cleanup_safe_git_residue,
    run_checkpoint_cleanup,
)
from .cleanup_orphans_cmd import inspect_orphans_command, salvage_orphan_command, task_display_token
from .cleanup_paths import cleanup_paths_command
from .cleanup_salvage import recover_orphan_task
from .cleanup_scope import get_project_id, iter_target_project_ids, iter_target_repos
from .cleanup_snapshots_cmd import (
    cleanup_snapshots_command,
    execute_snapshot_deletions,
    run_snapshot_deletions,
)
from .cleanup_status_payload import CleanupStatusDeps, build_cleanup_status_payload_impl

# Re-export for backward compatibility
__all__ = [
    "CheckpointAnalysis",
    "CleanupAction",
    "analyze_checkpoint",
    "app",
    "build_cleanup_status_payload",
    "cleanup_checkpoint",
    "cleanup_checkpoints",
    "cleanup_path",
    "cleanup_status",
    "format_analysis",
    "run_snapshot_deletions",
]

app = typer.Typer(
    help=(
        "Clean up git/checkpoint residue plus managed workspace leftovers.\n"
        "Read-only: status, checkpoints, inspect-orphans.\n"
        "Cleanup: checkpoints --auto, checkpoints --force, snapshots, cleanrooms.\n"
        "Scratch: reports old /srv/scratch entries; --apply deletes them (weekly in host maintenance).\n"
        "Path cleanup removes literal paths only. Globs are rejected and directories require --recursive."
    )
)

_NO_CLEANUP_FLAG_MSG = "Use --auto to cleanup safe cases or --force for all"
_DRY_RUN_MSG = "DRY RUN - No changes will be made:"
AutoOpt = Annotated[bool, typer.Option("--auto", help="Delete only SAFE/ALREADY_MERGED checkpoints.")]
ForceOpt = Annotated[bool, typer.Option("--force", help="Destructive checkpoint cleanup with confirm token.")]
StaleDaysOpt = Annotated[int, typer.Option("--stale-days", help="Mark checkpoints stale after N days.")]
DryRunOpt = Annotated[bool, typer.Option("--dry-run", help="Preview cleanup without deleting anything.")]
AllProjectsOpt = Annotated[bool, typer.Option("--all", help="Scan all managed projects.")]
ConfirmOpt = Annotated[str | None, typer.Option("--confirm", help="Single-use confirm token.")]
FailResidueOpt = Annotated[bool, typer.Option("--fail-on-residue", help="Exit 2 when cleanup debt remains.")]


_task_display_token = task_display_token


def _checkpoint_branch_name(checkpoint: Any) -> str:
    task_id = str(checkpoint.task_id)
    project_id = str(checkpoint.project_id)
    return resolve_task_branch(task_id, project_id=project_id)


def _cleanup_stale_checkpoint_metadata(project_id: str | None, dry_run: bool) -> int:
    """Prune checkpoint metadata whose branch has already gone away."""
    stale = get_stale_checkpoints(project_id)
    if dry_run:
        return len(stale)
    for checkpoint in stale:
        remove_snapshot(checkpoint.task_id, project_id=checkpoint.project_id)
    return len(stale)


def _print_stale_checkpoint_report(count: int, dry_run: bool) -> None:
    verb = "Would prune" if dry_run else "Pruned"
    typer.echo(f"  {verb} stale checkpoint metadata: {count}")


@app.callback()
def cleanup_callback(ctx: typer.Context) -> None:
    """Initialize context when the cleanup sub-app is invoked directly."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


_iter_target_repos = iter_target_repos
_iter_target_project_ids = iter_target_project_ids
_execute_snapshot_deletions = execute_snapshot_deletions


def _snapshot_residue_for_status(project_id: str) -> Sequence[Any]:
    try:
        return find_snapshot_residue([project_id], project_id=project_id)
    except SnapshotError as exc:
        if "Shared Btrfs workspaces are not available" in str(exc):
            return []
        raise


def build_cleanup_status_payload(
    all_projects: bool,
    *,
    project_id_override: str | None = None,
) -> dict[str, Any]:
    """Build the canonical cross-repo cleanup summary payload."""
    return build_cleanup_status_payload_impl(
        all_projects,
        project_id_override=project_id_override,
        deps=CleanupStatusDeps(
            get_project_id=_get_project_id_for_status,
            get_active_checkpoints=get_active_checkpoints,
            iter_target_repos=_iter_repos_for_status,
            branch_name=_checkpoint_branch_name,
            workspace_summary=build_repo_workspace_summary,
            stale_checkpoints=get_stale_checkpoints,
            snapshot_residue=_snapshot_residue_for_status,
        ),
    )


def _get_project_id_for_status(all_projects: bool, project_id_override: str | None = None) -> str | None:
    try:
        return get_project_id(all_projects, project_id_override)
    except TypeError:
        return get_project_id(all_projects)


def _iter_repos_for_status(all_projects: bool, project_id_override: str | None = None) -> list[Path]:
    try:
        return _iter_target_repos(all_projects, project_id_override)
    except TypeError:
        return _iter_target_repos(all_projects)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("checkpoints")
def cleanup_checkpoints(
    auto: AutoOpt = False,
    force: ForceOpt = False,
    stale_days: StaleDaysOpt = 7,
    dry_run: DryRunOpt = False,
    all_projects: AllProjectsOpt = False,
    confirm: ConfirmOpt = None,
) -> None:
    """Analyze active checkpoints and legacy residue; delete only with --auto or confirmed --force."""
    project_id = get_project_id(all_projects)
    checkpoints = get_active_checkpoints(project_id)
    stale_metadata = _cleanup_stale_checkpoint_metadata(project_id, dry_run) if auto and not force else 0

    if not checkpoints:
        counts = cleanup_safe_git_residue(_iter_target_repos(all_projects), dry_run) if auto else (0, 0, 0, 0, 0, 0)
        if auto and dry_run:
            typer.echo(_DRY_RUN_MSG)
        output_success("No checkpoint residue found")
        if auto:
            _print_stale_checkpoint_report(stale_metadata, dry_run)
            print_git_residue_report(*counts)
        return

    typer.echo(f"Analyzing {len(checkpoints)} checkpoint(s)...")
    analyses, categorization = analyze_and_display(checkpoints, stale_days)

    if not auto and not force:
        typer.echo("")
        typer.echo(_NO_CLEANUP_FLAG_MSG)
        return

    repos = _iter_target_repos(all_projects)

    if auto and not force:
        typer.echo("")
        if dry_run:
            typer.echo(_DRY_RUN_MSG)
        run_checkpoint_cleanup(categorization.safe_to_delete, force=False, dry_run=dry_run, repos=repos)
        _print_stale_checkpoint_report(stale_metadata, dry_run)
        return

    # --force requires two-pass confirmation
    command_key, preview_lines, cmd = build_force_checkpoint_preview(
        analyses,
        categorization,
        project_id,
        all_projects,
    )
    confirm_gate(command_key, confirm, preview_lines, cmd)

    typer.echo("")
    if dry_run:
        typer.echo(_DRY_RUN_MSG)
    run_checkpoint_cleanup(analyses, force=True, dry_run=dry_run, repos=repos)


@app.command("inspect-orphans")
def inspect_orphans(
    all_projects: AllProjectsOpt = False,
) -> None:
    """Inspect orphan task branches that need salvage or manual review."""
    inspect_orphans_command(
        _iter_target_repos(all_projects),
        all_projects=all_projects,
        assess=assess_orphan_task_branches,
    )


@app.command("salvage")
def salvage_orphan(
    task_id: Annotated[str, typer.Argument(help="Missing-task orphan branch to recover")],
    all_projects: AllProjectsOpt = False,
) -> None:
    """Recover a salvageable missing-task orphan branch into a normal task checkpoint."""
    salvage_orphan_command(
        task_id,
        _iter_target_repos(all_projects),
        assess=assess_orphan_task_branches,
        recover=recover_orphan_task,
    )


@app.command("snapshots")
def cleanup_snapshots(
    residue_name: Annotated[str | None, typer.Argument(help="Specific legacy snapshot residue to delete")] = None,
    all_projects: AllProjectsOpt = False,
    dry_run: DryRunOpt = False,
    confirm: ConfirmOpt = None,
) -> None:
    """Delete legacy snapshot residue with two-pass confirm-token flow."""
    cleanup_snapshots_command(
        residue_name,
        all_projects=all_projects,
        dry_run=dry_run,
        confirm=confirm,
        project_ids=_iter_target_project_ids(all_projects),
        current_project_id=get_project_id(all_projects),
    )


@app.command("status")
def cleanup_status(
    ctx: typer.Context,
    all_projects: AllProjectsOpt = False,
    fail_on_residue: FailResidueOpt = False,
) -> None:
    """Show cleanup debt for the current project or all managed projects."""
    result = build_cleanup_status_payload(all_projects)
    if ctx.obj.is_compact:
        format_cleanup_status_compact(result, all_projects)
    else:
        output_json(result)
    if fail_on_residue and result["summary"]["repos_needing_cleanup"] > 0:
        raise typer.Exit(2)


@app.command("path")
def cleanup_path(
    paths: Annotated[
        list[str],
        typer.Argument(help="Literal path(s) to remove (repo-relative or absolute). Globs are not allowed."),
    ],
    recursive: Annotated[bool, typer.Option("--recursive", help="Allow directory deletion.")] = False,
    dry_run: DryRunOpt = False,
) -> None:
    """Safely remove literal paths after repo and session guardrails pass."""
    cleanup_paths_command(paths, recursive=recursive, dry_run=dry_run)


@app.command("cleanrooms")
def cleanup_cleanrooms(
    older_than: Annotated[
        str, typer.Option("--older-than", help="Only jobs idle at least this long (e.g. 30m, 24h, 2d).")
    ] = "24h",
    project: Annotated[
        str | None, typer.Option("--project", help="Only jobs named <project>-cleanroom-*.")
    ] = None,
    dry_run: DryRunOpt = False,
) -> None:
    """Remove kept `st check cleanroom --keep-dir` job dirs from the cleanroom scratch parent."""
    try:
        min_age = cleanroom_prune.parse_age(older_than)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    parent = cleanroom_prune.cleanroom_parent()
    jobs = cleanroom_prune.find_cleanroom_jobs(parent, older_than=min_age, project=project)
    verb = "Would remove" if dry_run else "Removed"
    freed = 0
    removed = 0
    errors = 0
    typer.echo(f"Cleanroom parent: {parent}")
    for job in jobs:
        label = f"{job.path.name} ({cleanroom_prune.format_bytes(job.size_bytes)}, idle {job.age_seconds / 3600:.1f}h)"
        if job.skip_reason is not None:
            typer.echo(f"  Skipped {job.path.name}: {job.skip_reason}")
            continue
        if not dry_run:
            try:
                cleanroom_prune.remove_job(job)
            except (OSError, ValueError) as exc:
                errors += 1
                typer.echo(f"  ERROR {job.path.name}: {exc}", err=True)
                continue
        typer.echo(f"  {verb} {label}")
        removed += 1
        freed += job.size_bytes
    summary = f"{verb} {removed} cleanroom(s), {'would free' if dry_run else 'freed'} {cleanroom_prune.format_bytes(freed)}"
    if errors:
        output_error(f"{summary}; {errors} error(s)")
        raise typer.Exit(1)
    output_success(summary)


@app.command("scratch")
def cleanup_scratch(
    ctx: typer.Context,
    older_than: Annotated[
        str | None,
        typer.Option("--older-than", help="Minimum idle age (e.g. 72h, 7d). Default: host retention policy."),
    ] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Delete the candidates now instead of reporting them.")] = False,
) -> None:
    """Report /srv/scratch entries idle past the retention age; --apply deletes them.

    Host maintenance applies this weekly. Protected: cache/models/.dev-tools and
    st-* namespaces, symlink targets from ~ and project trees (depth 4, same
    filesystem), and paths open by any visible process. Age is the newest file
    mtime/ctime/atime or directory mtime/ctime in the entry.
    """
    from app.tasks._retention_scratch import apply_scratch_retention, collect_scratch_review
    from app.utils.host_retention_policy import HostRetentionPolicy

    try:
        hours = (cleanroom_prune.parse_age(older_than) / 3600 if older_than
                 else HostRetentionPolicy.from_env().scratch_review_max_age_hours)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    compact = bool(ctx.obj) and getattr(ctx.obj, "is_compact", True)
    if apply:
        applied = apply_scratch_retention(max_age_hours=int(hours))
        if not compact:
            output_json(applied)
            return
        for path in applied["deleted_paths"]:
            typer.echo(f"  deleted {path}")
        for skip in applied["kept"]:
            typer.echo(f"  kept    {skip['path']}: {skip['reason']}")
        output_success(f"{len(applied['deleted_paths'])} deleted, {cleanroom_prune.format_bytes(applied['bytes_reclaimed'])} reclaimed; "
                       f"{applied['protected']} protected")
        if applied["status"] == "partial":
            raise typer.Exit(1)
        return
    review = collect_scratch_review(max_age_hours=int(hours))
    if not compact:
        output_json(review)
        return
    typer.echo(f"REPORT ONLY - nothing deleted (host maintenance applies weekly; --apply now). Root: {review['root']} (idle >= {review['max_age_hours']}h)")
    for item in review["candidates"]:
        typer.echo(f"  review {item['path']} ({cleanroom_prune.format_bytes(item['size_bytes'])}, idle {item['age_hours']}h)")
    for skip in review["protected"]:
        typer.echo(f"  keep   {skip['path']}: {skip['reason']}")
    total = sum(item["size_bytes"] for item in review["candidates"])
    visibility = "" if review["process_visibility"] == "complete" else "; process visibility partial"
    output_success(
        f"{len(review['candidates'])} review candidate(s), {cleanroom_prune.format_bytes(total)}; "
        f"{len(review['protected'])} protected, {review['recent']} recent{visibility}"
    )
