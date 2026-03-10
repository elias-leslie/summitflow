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
from .cleanup_git import has_uncommitted_changes
from .cleanup_handlers import (
    categorize_worktrees,
    confirm_force_cleanup,
    execute_cleanup,
    print_cleanup_results,
    print_worktree_summary,
)
from .cleanup_paths import cleanup_paths_command

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

# Messages
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


def _categorize_analyses(analyses: list) -> tuple[list, list, list]:
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


def _build_repo_cleanup_entry(repo_path: Path) -> dict[str, Any]:
    """Build cleanup counters for one managed repository."""
    project_id = repo_path.name
    workspace_summary = build_repo_workspace_summary(repo_path)
    active_worktrees = get_active_worktrees(project_id)
    client = STClient(require_project=False)
    analyses = [analyze_worktree(worktree, client) for worktree in active_worktrees]
    dirty_worktrees = sum(1 for wt in active_worktrees if has_uncommitted_changes(wt.path))
    needs_merge_tasks, conflict_tasks, review_tasks = _categorize_analyses(analyses)
    needs_cleanup = any((
        dirty_worktrees, workspace_summary.orphan_branches, workspace_summary.prunable_branches,
        needs_merge_tasks, conflict_tasks, review_tasks,
    ))
    return {
        "project_id": project_id,
        "path": str(repo_path),
        "active_worktrees": workspace_summary.active_worktrees,
        "dirty_worktrees": dirty_worktrees,
        "orphan_task_branches": workspace_summary.orphan_branches,
        "prunable_task_branches": workspace_summary.prunable_branches,
        "worktree_task_ids": workspace_summary.worktree_task_ids,
        "orphan_branch_names": workspace_summary.orphan_branch_names,
        "prunable_branch_names": workspace_summary.prunable_branch_names,
        "salvage_task_ids": workspace_summary.salvage_task_ids,
        "review_orphan_task_ids": workspace_summary.review_orphan_task_ids,
        "needs_merge_count": len(needs_merge_tasks),
        "conflict_count": len(conflict_tasks),
        "review_count": len(review_tasks),
        "needs_merge_tasks": needs_merge_tasks[:3],
        "conflict_tasks": conflict_tasks[:3],
        "review_tasks": review_tasks[:3],
        "needs_cleanup": needs_cleanup,
    }


def build_cleanup_status_payload(all_projects: bool) -> dict[str, Any]:
    """Build the canonical cross-repo cleanup summary payload."""
    project_id = get_project_id(all_projects)
    worktrees = get_active_worktrees(project_id)
    repositories = [_build_repo_cleanup_entry(repo_path) for repo_path in _iter_target_repos(all_projects)]

    summary = {
        "repos": len(repositories),
        "repos_needing_cleanup": sum(1 for repo in repositories if repo["needs_cleanup"]),
        "active_worktrees": sum(repo["active_worktrees"] for repo in repositories),
        "dirty_worktrees": sum(repo["dirty_worktrees"] for repo in repositories),
        "orphan_task_branches": sum(repo["orphan_task_branches"] for repo in repositories),
        "prunable_task_branches": sum(repo["prunable_task_branches"] for repo in repositories),
    }

    return {
        "summary": summary,
        "repositories": repositories,
        "worktrees": [
            {
                "task_id": wt.task_id,
                "path": str(wt.path),
                "branch": wt.branch,
                "base_branch": wt.base_branch,
                "project_id": wt.project_id,
            }
            for wt in worktrees
        ],
        "total": len(worktrees),
    }


def _print_repo_compact(repo: dict[str, Any]) -> None:
    """Print compact status line for one repo entry."""
    if not repo["needs_cleanup"] and not repo["active_worktrees"]:
        print(f"{repo['project_id']} clean")
        return
    preview = f" tasks:{','.join(repo['worktree_task_ids'])}" if repo["worktree_task_ids"] else ""
    attention_parts: list[str] = []
    if repo["needs_merge_tasks"]:
        attention_parts.append(f"finalize:{','.join(repo['needs_merge_tasks'])}")
    if repo["conflict_tasks"]:
        attention_parts.append(f"conflicts:{','.join(repo['conflict_tasks'])}")
    if repo["review_tasks"]:
        attention_parts.append(f"review:{','.join(repo['review_tasks'])}")
    if repo["salvage_task_ids"]:
        attention_parts.append(f"salvage:{','.join(repo['salvage_task_ids'])}")
    if repo["review_orphan_task_ids"]:
        attention_parts.append(f"review_orphans:{','.join(repo['review_orphan_task_ids'])}")
    attention = f" {' '.join(attention_parts)}" if attention_parts else ""
    branch_parts: list[str] = []
    if repo["prunable_branch_names"]:
        branch_parts.append(f"prune_branches:{','.join(repo['prunable_branch_names'])}")
    if repo["orphan_branch_names"]:
        branch_parts.append(f"orphan_branches:{','.join(repo['orphan_branch_names'])}")
    branch_preview = f" {' '.join(branch_parts)}" if branch_parts else ""
    print(
        f"{repo['project_id']} worktrees:{repo['active_worktrees']} "
        f"dirty:{repo['dirty_worktrees']} orphan:{repo['orphan_task_branches']} "
        f"prunable:{repo['prunable_task_branches']}{preview}{attention}{branch_preview}"
    )


def format_cleanup_status_compact(data: dict[str, Any], all_projects: bool) -> None:
    """Emit TOON summary for cleanup status."""
    summary = data["summary"]
    scope = "all" if all_projects else "current"
    print(
        "CLEANUP[{scope}]:repos={repos} needs_cleanup={needs} worktrees={worktrees} "
        "dirty={dirty} orphan={orphan} prunable={prunable}".format(
            scope=scope,
            repos=summary["repos"],
            needs=summary["repos_needing_cleanup"],
            worktrees=summary["active_worktrees"],
            dirty=summary["dirty_worktrees"],
            orphan=summary["orphan_task_branches"],
            prunable=summary["prunable_task_branches"],
        )
    )
    for repo in data["repositories"]:
        _print_repo_compact(repo)


def _analyze_and_display(worktrees: list, client: STClient, stale_days: int) -> tuple:
    """Analyze worktrees, print summary, and return (analyses, categorization)."""
    analyses = [analyze_worktree(wt, client) for wt in worktrees]
    categorization = categorize_worktrees(analyses, stale_days)
    print_worktree_summary(len(worktrees), categorization, stale_days)
    for analysis in analyses:
        typer.echo(format_analysis(analysis))
    return analyses, categorization


def _run_cleanup(analyses: list, categorization, force: bool, dry_run: bool) -> None:
    """Execute cleanup and print results."""
    typer.echo("")
    if dry_run:
        typer.echo(_DRY_RUN_MSG)
    targets = analyses if force else categorization.safe_to_delete
    results = execute_cleanup(targets, force=force, dry_run=dry_run)
    print_cleanup_results(results, dry_run)


def _cleanup_safe_git_residue(repos: list[Path], dry_run: bool) -> tuple[int, int, int, int]:
    """Prune stale worktree registrations and safe orphan task branches."""
    if dry_run:
        return (0, 0, 0, 0)

    pruned_worktree_registrations = 0
    pruned_task_branches = 0
    pruned_equivalent_task_branches = 0
    pruned_closed_task_branches = 0
    for repo_path in repos:
        prune_worktree_registrations(repo_path)
        pruned_worktree_registrations += 1
        pruned_task_branches += len(prune_prunable_task_branches(repo_path))
        pruned_equivalent_task_branches += len(prune_equivalent_orphan_task_branches(repo_path))
        pruned_closed_task_branches += len(prune_closed_orphan_task_branches(repo_path))

    return (
        pruned_worktree_registrations,
        pruned_task_branches,
        pruned_equivalent_task_branches,
        pruned_closed_task_branches,
    )


def _get_orphan_assessment(repo_path: Path, task_id: str) -> Any | None:
    """Return orphan assessment for task_id in repo_path, if any."""
    for item in assess_orphan_task_branches(repo_path):
        if item.task_id == task_id:
            return item
    return None


def _get_branch_subject(repo_path: Path, branch_name: str) -> str | None:
    """Return the latest commit subject for a branch."""
    result = run_git(["log", "-1", "--format=%s", branch_name], repo_path)
    if result.returncode != 0:
        return None
    subject = result.stdout.strip()
    return subject or None


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
    force: Annotated[bool, typer.Option("--force", help="Force cleanup all worktrees (with confirmation)")] = False,
    stale_days: Annotated[int, typer.Option("--stale-days", help="Consider worktrees stale after N days")] = 7,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be cleaned up without doing it")] = False,
    all_projects: Annotated[bool, typer.Option("--all", help="Scan all projects (default: current project only)")] = False,
) -> None:
    """List orphaned/stale worktrees with cleanup recommendations.

    Actions: SAFE, MERGED, NEEDS_MERGE, CONFLICT, REVIEW, ACTIVE.
    Examples: --auto (safe cases), --force (all), --stale-days N, --dry-run.
    """
    project_id = get_project_id(all_projects)
    worktrees = get_active_worktrees(project_id)

    if not worktrees:
        if auto:
            pruned_worktree_registrations, pruned_task_branches, pruned_equivalent_task_branches, pruned_closed_task_branches = _cleanup_safe_git_residue(
                _iter_target_repos(all_projects),
                dry_run=dry_run,
            )
            if dry_run:
                typer.echo(_DRY_RUN_MSG)
            output_success("No worktrees found")
            typer.echo(f"  Pruned git worktree registrations in {pruned_worktree_registrations} repo(s)")
            typer.echo(f"  Pruned merged orphan task branches: {pruned_task_branches}")
            typer.echo(f"  Pruned equivalent orphan task branches: {pruned_equivalent_task_branches}")
            typer.echo(f"  Pruned closed orphan task branches: {pruned_closed_task_branches}")
            return
        output_success("No worktrees found")
        return

    typer.echo(f"Analyzing {len(worktrees)} worktree(s)...")
    client = STClient(require_project=False)
    analyses, categorization = _analyze_and_display(worktrees, client, stale_days)

    if not auto and not force:
        typer.echo("")
        typer.echo(_NO_CLEANUP_FLAG_MSG)
        return

    if force and not dry_run and not confirm_force_cleanup(len(worktrees), len(categorization.needs_merge)):
        typer.echo(_ABORTED_MSG)
        return

    _run_cleanup(analyses, categorization, force=force, dry_run=dry_run)
    pruned_worktree_registrations, pruned_task_branches, pruned_equivalent_task_branches, pruned_closed_task_branches = _cleanup_safe_git_residue(
        _iter_target_repos(all_projects),
        dry_run=dry_run,
    )
    if auto and not dry_run:
        typer.echo(f"  Pruned git worktree registrations in {pruned_worktree_registrations} repo(s)")
        typer.echo(f"  Pruned merged orphan task branches: {pruned_task_branches}")
        typer.echo(f"  Pruned equivalent orphan task branches: {pruned_equivalent_task_branches}")
        typer.echo(f"  Pruned closed orphan task branches: {pruned_closed_task_branches}")


@app.command("inspect-orphans")
def inspect_orphans(
    all_projects: Annotated[bool, typer.Option("--all", help="Inspect all managed projects")] = False,
) -> None:
    """Inspect unresolved orphan task branches that need salvage or review."""
    lines: list[str] = []
    salvage_count = 0
    review_count = 0
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
            flag_text = ",".join(flags) if flags else "-"
            lines.append(
                f"{repo_path.name} {item.task_id} branch:{item.branch_name} "
                f"resolution:{item.resolution} task:{item.task_status or 'missing'} "
                f"ahead:{item.commits_ahead} files:{item.files_changed} flags:{flag_text}"
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
    match: tuple[Path, Any] | None = None
    for repo_path in repos:
        item = _get_orphan_assessment(repo_path, task_id)
        if item is not None:
            match = (repo_path, item)
            break

    if match is None:
        output_error(
            f"No unresolved orphan branch found for {task_id}. "
            "Use `st cleanup inspect-orphans` to find salvage candidates."
        )
        raise typer.Exit(1)

    repo_path, item = match
    if item.resolution != "salvage" or item.task_status is not None:
        output_error(
            f"{task_id} is not a missing-task salvage candidate. "
            "This command only restores orphan branches whose task record is gone."
        )
        raise typer.Exit(1)

    title = _get_branch_subject(repo_path, item.branch_name) or f"Recover orphan branch {task_id}"
    description = _build_salvage_description(task_id, item.branch_name, repo_path)
    created = task_store.create_task(
        project_id=repo_path.name,
        title=title,
        description=description,
        task_id=task_id,
        labels=["cleanup:salvaged"],
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
    paths: Annotated[list[str], typer.Argument(help="Literal repo-relative path(s) to remove")],
    recursive: Annotated[
        bool,
        typer.Option("--recursive", help="Allow directory deletion"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be deleted without deleting it"),
    ] = False,
) -> None:
    """Safely remove repo-local paths with guardrails."""
    cleanup_paths_command(paths, recursive=recursive, dry_run=dry_run)
