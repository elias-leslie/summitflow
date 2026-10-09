"""Canonical VCS hygiene commands for agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from app.storage.connection import get_cursor
from app.utils._git_branches import list_safe_task_refs
from app.utils._git_core import fetch_repository, pull_repository

from ..details import display_path, write_details
from ..lib.usage import usage
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
        "Canonical VCS hygiene and isolated exact-source publication. Prefer "
        "`st vcs doctor` and `st vcs reconcile` over separate status sweeps."
    )
)


@app.command("publication")
@usage(surface="st.vcs.publication", cmd="st vcs publication", when="read retained manual publication and finding status",
       precautions=("read-only; unknown is not passing CI",), tier="reference")
def publication_status() -> None:
    """Read-only lightweight startup status, without a network CI wait."""
    from app.services.publication_health import (
        format_publication_health,
        get_project_publication_health,
    )
    from cli.config import get_config_optional

    project_id = get_config_optional().project_id
    if not project_id:
        typer.echo("Manual publication: unknown; no registered project for this directory.")
        return
    try:
        health = get_project_publication_health(project_id)
        typer.echo(format_publication_health(health))
    except Exception:
        typer.echo("Manual publication: unknown; status unavailable. Inspect ST before claiming completion.")


@app.command("publish")
@usage(surface="st.vcs.publish", cmd="st vcs publish --source ID --sha FULL_OID --now",
       when="owner-authorized immediate publication of an accepted exact commit",
       precautions=("requires explicit publication authority; never creates commits or reconciles the checkout",
                    "acceptance, outgoing-history and actual repository requirements remain guarded"), tier="reference")
def publish_now(
    source: Annotated[str, typer.Option("--source", help="Registered project ID (or existing project source ID)")],
    sha: Annotated[str, typer.Option("--sha", help="Exact accepted lowercase full commit OID")],
    now: Annotated[bool, typer.Option("--now", help="Explicit owner-triggered publication of the supplied source")] = False,
    authorize_workflow: Annotated[list[str] | None, typer.Option("--authorize-workflow", help="Explicit authority for a listed workflow: exact path for selected source, BASE_SHA:path for a different base workflow; repeat as needed")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Show the complete retained structured observation")] = False,
) -> None:
    """Publish an exact accepted source in isolation and retain its real CI evidence."""
    if not now:
        typer.echo("Immediate publication requires --now and explicit owner authorization; no scheduled publication runs.")
        raise typer.Exit(2)
    from app.tasks.backup_manual_publish import publish_project_now

    try:
        result = publish_project_now(source, sha, authorized_workflows=tuple(authorize_workflow)) if authorize_workflow else publish_project_now(source, sha)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from None
    except Exception:
        # Transport/DB errors can contain credentials. Never print raw diagnostics.
        typer.echo("Publication could not establish durable evidence. Inspect canonical publication health before retrying.")
        raise typer.Exit(2) from None
    from app.tasks.backup_publish import _public_evidence

    safe_result = _public_evidence(result)
    if json_output:
        output_json(safe_result)
    else:
        details = write_details(Path.cwd(), "publication", json.dumps(safe_result, indent=2, sort_keys=True))
        delivery = result.get("delivery") or {}
        complete = bool(result.get("publication_complete") and result.get("evidence_recorded"))
        output_json({"outcome": result.get("status", "completed" if complete else "pending"),
                     "source": sha, "uploaded_source": delivery.get("uploaded_source"),
                     "pull_request": delivery.get("pull_request_state", "unknown"),
                     "merged_source": delivery.get("merged_source"),
                     "blockers": [] if complete else [result.get("reason", "publication_evidence_incomplete")],
                     "unauthorized_workflows": result.get("unauthorized_workflows", []),
                     "next_action": "none" if complete else "Inspect retained evidence; explicitly reobserve this source after resolving the blocker",
                     "evidence": result.get("evidence"), "details": display_path(Path.cwd(), details)})
    if not (result.get("publication_complete") and result.get("evidence_recorded")):
        raise typer.Exit(2)

_IGNORED_WORKSPACE_REPO_NAMES = frozenset({"claude-config", "codex-config"})


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


def _discover_unmanaged_repos(repos: list[Path]) -> list[Path]:
    projects_dir = get_projects_base_dir()
    if not projects_dir.is_dir():
        return []
    managed = {p.resolve() for p in repos if p.exists()}
    discovered: list[Path] = []
    for child in sorted(projects_dir.iterdir()):
        if child.name in _IGNORED_WORKSPACE_REPO_NAMES:
            continue
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
    cleanup_payload: dict[str, Any],
    unmanaged: list[Path],
    task_refs: list[dict[str, Any]],
) -> list[VcsIssue]:
    issues: list[VcsIssue] = []
    for row in git_rows:
        repo = str(row.get("name") or "?")
        if int(row.get("uncommitted") or 0):
            issues.append(VcsIssue(repo, "dirty", f"uncommitted:{row['uncommitted']}", "git diff"))
        # Unpublished local history is normal. Keep counts in the summary, not
        # blockers that pressure agents into publishing unrelated work.
        if int(row.get("behind") or 0):
            issues.append(VcsIssue(repo, "behind", f"behind:{row['behind']}", "st vcs reconcile"))
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
        "cleanup": int(cleanup_summary["repos_needing_cleanup"]),
        "unmanaged": len(unmanaged),
        "task_refs": len(task_refs),
    }


def _details_text(
    *,
    summary: dict[str, int],
    sync: list[dict[str, Any]],
    git_rows: list[dict[str, Any]],
    cleanup_payload: dict[str, Any],
    unmanaged: list[Path],
    task_refs: list[dict[str, Any]],
    issues: list[VcsIssue],
) -> str:
    payload = {
        "summary": summary,
        "sync": sync,
        "git": git_rows,
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
        f"ahead={summary['ahead']} behind={summary['behind']} "
        f"cleanup={summary['cleanup']} unmanaged={summary['unmanaged']} "
        f"task_refs={summary['task_refs']} blockers={len(issues)} details:{display_path(Path.cwd(), details)}"
    )
    for issue in issues[:8]:
        print(f"BLOCKER:{issue.repo}:{issue.kind}:{issue.detail}|next:{issue.next_action}")
    if len(issues) > 8:
        print(f"BLOCKER:more:{len(issues) - 8}|details:{display_path(Path.cwd(), details)}")


def _run_doctor(*, all_projects: bool, fetch: bool) -> tuple[dict[str, Any], list[VcsIssue], Path]:
    repos = _target_repos(all_projects)
    sync = [fetch_repository(repo).model_dump(exclude_none=True) for repo in repos] if fetch else []
    git_rows = _status_rows(repos)
    cleanup = _cleanup_payload(all_projects)
    unmanaged = _discover_unmanaged_repos(repos) if all_projects else []
    task_refs = _safe_task_ref_rows(repos)
    summary = _summary(repos, git_rows, cleanup, unmanaged, task_refs)
    issues = _issues(git_rows, cleanup, unmanaged, task_refs)
    details = write_details(
        Path.cwd(),
        "vcs-doctor",
        _details_text(
            summary=summary,
            sync=sync,
            git_rows=git_rows,
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
        typer.Option("--fetch/--no-fetch", help="Fetch Git remotes before reporting."),
    ] = False,
    fail_on_issues: Annotated[
        bool,
        typer.Option("--fail-on-issues/--no-fail", help="Exit 2 when VCS debt remains."),
    ] = True,
) -> None:
    """Report Git, cleanup, and unmanaged-repo debt in one compact check."""
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
@usage(
    surface="st.vcs.reconcile",
    cmd="st vcs reconcile",
    when="explicit remote synchronization and VCS residue reconciliation",
    precautions=(
        "this command pulls remotes and may delete already-integrated remote task refs; use only when that remote operation is intended",
        "use st vcs doctor for local inspection; unpublished local commits are normal, not debt",
        "preserve ownerless work; inspect before cleanup, and publish only when requested",
    ),
    task_types=("devops", "config"),
    tier="reference",
)
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
