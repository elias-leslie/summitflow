"""Canonical VCS hygiene commands for agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from app.storage.connection import get_cursor
from app.utils._git_branches import list_safe_task_refs
from app.utils._git_core import pull_repository

from ..details import display_path, write_details
from ..lib.jj import JJError, is_colocated, run_jj, status_summary
from ..lib.workspace_paths import get_projects_base_dir
from ..output import output_json
from ..output_context import OutputContext
from ._git_helpers import _get_managed_repos, _get_repo_status
from .cleanup import (
    _cleanup_stale_checkpoint_metadata,
    _iter_target_repos,
    build_cleanup_status_payload,
)
from .cleanup_handlers import cleanup_safe_git_residue

app = typer.Typer(
    help=(
        "Canonical VCS hygiene. Prefer `st vcs doctor` and `st vcs reconcile` "
        "over separate git/jj/cleanup status sweeps."
    )
)


@dataclass(frozen=True)
class VcsIssue:
    repo: str
    kind: str
    detail: str
    next_action: str


@app.callback()
def vcs_callback(ctx: typer.Context) -> None:
    """Initialize context when the vcs sub-app is invoked directly."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _target_repos(all_projects: bool) -> list[Path]:
    repos = _get_managed_repos()
    if all_projects:
        return repos
    cwd = Path.cwd().resolve()
    for repo in repos:
        try:
            cwd.relative_to(repo)
            return [repo]
        except ValueError:
            continue
    return repos[:1] if repos else []


def _fetch_jj_repos(repos: list[Path]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for repo in repos:
        if not is_colocated(repo):
            continue
        result = run_jj(repo, ["git", "fetch", "--remote", "origin"])
        results.append(
            {
                "repo": repo.name,
                "status": "ok" if result.returncode == 0 else "failed",
                "detail": (result.stderr or result.stdout).strip(),
            }
        )
    return results


def _discover_unmanaged_repos(repos: list[Path]) -> list[Path]:
    projects_dir = get_projects_base_dir()
    if not projects_dir.is_dir():
        return []
    managed = {p.resolve() for p in repos if p.exists()}
    discovered: list[Path] = []
    for child in sorted(projects_dir.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        resolved = child.resolve()
        if resolved not in managed:
            discovered.append(resolved)
    return discovered


def _register_workspace_repo(repo: Path) -> str:
    with get_cursor() as cur:
        cur.execute("SELECT id FROM backup_sources WHERE id = %s", (repo.name,))
        existing = cur.fetchone()
        if existing:
            return "exists"
        cur.execute(
            """
            INSERT INTO backup_sources
                (id, name, path, source_type, project_id, enabled, frequency, retention_days)
            VALUES
                (%s, %s, %s, 'workspace', NULL, true, 'daily', 30)
            """,
            (repo.name, repo.name.replace("-", " ").title(), str(repo)),
        )
    return "registered"


def _status_rows(repos: list[Path]) -> list[dict[str, Any]]:
    return [status for repo in repos if (status := _get_repo_status(repo))]


def _jj_rows(repos: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for repo in repos:
        if not repo.exists():
            continue
        try:
            rows.append(status_summary(repo).__dict__)
        except JJError as exc:
            rows.append(
                {
                    "repo": repo.name,
                    "path": str(repo),
                    "branch": "-",
                    "colocated": False,
                    "state": "failed",
                    "described": False,
                    "conflicted": False,
                    "unpublished": 0,
                    "error": str(exc),
                }
            )
    return rows


def _cleanup_payload(all_projects: bool) -> dict[str, Any]:
    return build_cleanup_status_payload(all_projects)


def _safe_task_ref_rows(repos: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for repo in repos:
        if not repo.exists():
            continue
        for ref in list_safe_task_refs(repo):
            rows.append(
                {
                    "repo": repo.name,
                    "path": str(repo),
                    "name": ref.name,
                    "ref": ref.ref,
                    "kind": ref.kind,
                    "reason": ref.reason,
                    "remote": ref.remote,
                }
            )
    return rows


def _issues(
    git_rows: list[dict[str, Any]],
    jj_rows: list[dict[str, Any]],
    cleanup_payload: dict[str, Any],
    unmanaged: list[Path],
    task_refs: list[dict[str, Any]],
) -> list[VcsIssue]:
    issues: list[VcsIssue] = []
    for row in git_rows:
        repo = str(row.get("name") or "?")
        if int(row.get("uncommitted") or 0):
            issues.append(VcsIssue(repo, "dirty", f"uncommitted:{row['uncommitted']}", f"st -P {repo} jj diff"))
        if int(row.get("ahead") or 0):
            issues.append(VcsIssue(repo, "ahead", f"ahead:{row['ahead']}", f"st commit -R {row['path']} --push -m '<message>'"))
        if int(row.get("behind") or 0):
            issues.append(VcsIssue(repo, "behind", f"behind:{row['behind']}", "st vcs reconcile"))
    for row in jj_rows:
        repo = str(row.get("repo") or "?")
        if row.get("conflicted"):
            issues.append(VcsIssue(repo, "conflict", "jj_conflict:true", f"st -P {repo} jj conflicts"))
        if int(row.get("unpublished") or 0):
            issues.append(VcsIssue(repo, "unpublished", f"unpublished:{row['unpublished']}", f"st commit -R {row['path']} --push -m '<message>'"))
        state = str(row.get("state") or "")
        if state in {"dirty", "undescribed", "described", "failed"}:
            issues.append(VcsIssue(repo, "jj_state", f"state:{state}", f"st -P {repo} jj status"))
    for repo in cleanup_payload["repositories"]:
        if not repo["needs_cleanup"] and not repo["active_checkpoints"]:
            continue
        project_id = repo["project_id"]
        detail = (
            f"checkpoints:{repo['active_checkpoints']} dirty:{repo['dirty_checkpoints']} "
            f"main_dirty:{int(bool(repo.get('dirty_main_repo')))} "
            f"stale:{repo['stale_checkpoints']} snap:{repo['snapshot_residue']} "
            f"orphan:{repo['orphan_task_branches']} prunable:{repo['prunable_task_branches']}"
        )
        issues.append(VcsIssue(project_id, "cleanup", detail, f"st -P {project_id} cleanup status"))
    for repo in unmanaged:
        issues.append(VcsIssue(repo.name, "unmanaged", str(repo), "st vcs reconcile"))
    refs_by_repo: dict[str, list[dict[str, Any]]] = {}
    for ref in task_refs:
        refs_by_repo.setdefault(str(ref["repo"]), []).append(ref)
    for repo, refs in sorted(refs_by_repo.items()):
        local_count = sum(1 for ref in refs if ref["kind"] == "local")
        remote_count = sum(1 for ref in refs if ref["kind"] == "remote")
        issues.append(
            VcsIssue(
                repo,
                "task_refs",
                f"safe_local:{local_count} safe_remote:{remote_count}",
                "st vcs reconcile",
            )
        )
    return issues


def _summary(
    repos: list[Path],
    git_rows: list[dict[str, Any]],
    jj_rows: list[dict[str, Any]],
    cleanup_payload: dict[str, Any],
    unmanaged: list[Path],
    task_refs: list[dict[str, Any]],
) -> dict[str, int]:
    cleanup_summary = cleanup_payload["summary"]
    return {
        "repos": len(repos),
        "dirty": sum(1 for row in git_rows if int(row.get("uncommitted") or 0)),
        "ahead": sum(int(row.get("ahead") or 0) for row in git_rows),
        "behind": sum(int(row.get("behind") or 0) for row in git_rows),
        "unpublished": sum(int(row.get("unpublished") or 0) for row in jj_rows),
        "conflicts": sum(1 for row in jj_rows if row.get("conflicted")),
        "cleanup": int(cleanup_summary["repos_needing_cleanup"]),
        "unmanaged": len(unmanaged),
        "task_refs": len(task_refs),
    }


def _details_text(
    *,
    summary: dict[str, int],
    sync: list[dict[str, Any]],
    git_rows: list[dict[str, Any]],
    jj_rows: list[dict[str, Any]],
    cleanup_payload: dict[str, Any],
    unmanaged: list[Path],
    task_refs: list[dict[str, Any]],
    issues: list[VcsIssue],
) -> str:
    payload = {
        "summary": summary,
        "sync": sync,
        "git": git_rows,
        "jj": jj_rows,
        "cleanup": cleanup_payload,
        "unmanaged": [str(repo) for repo in unmanaged],
        "task_refs": task_refs,
        "issues": [issue.__dict__ for issue in issues],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _print_compact(label: str, summary: dict[str, int], issues: list[VcsIssue], details: Path) -> None:
    status = "OK" if not issues else "ISSUES"
    print(
        f"{label}:{status} repos={summary['repos']} dirty={summary['dirty']} "
        f"ahead={summary['ahead']} behind={summary['behind']} unpublished={summary['unpublished']} "
        f"conflicts={summary['conflicts']} cleanup={summary['cleanup']} unmanaged={summary['unmanaged']} "
        f"task_refs={summary['task_refs']} blockers={len(issues)} details:{display_path(Path.cwd(), details)}"
    )
    for issue in issues[:8]:
        print(f"BLOCKER:{issue.repo}:{issue.kind}:{issue.detail}|next:{issue.next_action}")
    if len(issues) > 8:
        print(f"BLOCKER:more:{len(issues) - 8}|details:{display_path(Path.cwd(), details)}")


def _run_doctor(*, all_projects: bool, fetch: bool) -> tuple[dict[str, Any], list[VcsIssue], Path]:
    repos = _target_repos(all_projects)
    sync = _fetch_jj_repos(repos) if fetch else []
    git_rows = _status_rows(repos)
    jj_rows = _jj_rows(repos)
    cleanup = _cleanup_payload(all_projects)
    unmanaged = _discover_unmanaged_repos(repos) if all_projects else []
    task_refs = _safe_task_ref_rows(repos)
    summary = _summary(repos, git_rows, jj_rows, cleanup, unmanaged, task_refs)
    issues = _issues(git_rows, jj_rows, cleanup, unmanaged, task_refs)
    details = write_details(
        Path.cwd(),
        "vcs-doctor",
        _details_text(
            summary=summary,
            sync=sync,
            git_rows=git_rows,
            jj_rows=jj_rows,
            cleanup_payload=cleanup,
            unmanaged=unmanaged,
            task_refs=task_refs,
            issues=issues,
        ),
    )
    result = {"summary": summary, "issues": [issue.__dict__ for issue in issues], "details": str(details)}
    return result, issues, details


@app.command()
def doctor(
    ctx: typer.Context,
    all_projects: Annotated[
        bool,
        typer.Option("--all/--current", help="Check all managed repos or only the current repo."),
    ] = True,
    fetch: Annotated[
        bool,
        typer.Option("--fetch/--no-fetch", help="Fetch jj remote bookmark state before reporting."),
    ] = True,
    fail_on_issues: Annotated[
        bool,
        typer.Option("--fail-on-issues/--no-fail", help="Exit 2 when VCS debt remains."),
    ] = True,
) -> None:
    """Report Git, jj, cleanup, and unmanaged-repo debt in one compact check."""
    result, issues, details = _run_doctor(all_projects=all_projects, fetch=fetch)
    if ctx.obj.is_compact:
        _print_compact("VCS", result["summary"], issues, details)
    else:
        output_json(result)
    if fail_on_issues and issues:
        raise typer.Exit(2)


def _sync_repos(repos: list[Path]) -> list[dict[str, Any]]:
    return [pull_repository(repo).model_dump(exclude_none=True) for repo in repos]


def _register_unmanaged(repos: list[Path]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for repo in _discover_unmanaged_repos(repos):
        results.append({"repo": repo.name, "path": str(repo), "status": _register_workspace_repo(repo)})
    return results


@app.command()
def reconcile(
    ctx: typer.Context,
    all_projects: Annotated[
        bool,
        typer.Option("--all/--current", help="Reconcile all managed repos or only the current repo."),
    ] = True,
    fail_on_issues: Annotated[
        bool,
        typer.Option("--fail-on-issues/--no-fail", help="Exit 2 when VCS debt remains after safe fixes."),
    ] = True,
) -> None:
    """Run safe VCS reconciliation: sync, register workspace repos, prune safe residue."""
    initial_repos = _target_repos(all_projects)
    registered = _register_unmanaged(initial_repos) if all_projects else []
    repos = _target_repos(all_projects)
    sync = _sync_repos(repos)
    project_id = None if all_projects or not repos else repos[0].name
    stale_pruned = _cleanup_stale_checkpoint_metadata(project_id, dry_run=False)
    residue_pruned = cleanup_safe_git_residue(_iter_target_repos(all_projects), dry_run=False)
    result, issues, details = _run_doctor(all_projects=all_projects, fetch=True)
    summary = dict(result["summary"])
    summary["registered"] = sum(1 for item in registered if item["status"] == "registered")
    summary["synced"] = sum(1 for item in sync if item["status"] in {"up_to_date", "updated"})
    summary["stale_pruned"] = stale_pruned
    summary["residue_pruned"] = sum(residue_pruned)
    if ctx.obj.is_compact:
        _print_compact("VCS-RECONCILE", summary, issues, details)
    else:
        output_json(
            {
                "summary": summary,
                "sync": sync,
                "registered": registered,
                "residue_pruned": residue_pruned,
                "issues": [issue.__dict__ for issue in issues],
                "details": str(details),
            }
        )
    if fail_on_issues and issues:
        raise typer.Exit(2)
