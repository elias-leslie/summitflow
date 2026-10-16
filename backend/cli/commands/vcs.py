"""Canonical VCS hygiene commands for agents."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
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
        "Canonical VCS hygiene and exact-source publication. Prefer "
        "`st vcs doctor` and `st vcs reconcile` over separate status sweeps."
    )
)


@app.command("publication")
@usage(surface="st.vcs.publication", cmd="st vcs publication [--mode nightly|manual] [--hold [--through SHA] | --release] [--reobserve]",
       when="read publication status; set auto or manual publication; hold commits local; replay the retained receipt",
       precautions=("nightly pushes hourly: private repos their head, public repos their newest accepted commit",
                    "--reobserve replays only the newest retained receipt; it never fetches or publishes"),
       tier="reference")
def publication_status(
    mode: Annotated[str | None, typer.Option("--mode", help="Set publication: nightly (hourly push) or manual")] = None,
    hold: Annotated[bool, typer.Option("--hold", help="Keep committed work local until released")] = False,
    through: Annotated[str | None, typer.Option("--through", help="With --hold: still publish up to this commit")] = None,
    reason: Annotated[str, typer.Option("--reason", help="With --hold: why later commits must stay local")] = "owner hold",
    release: Annotated[bool, typer.Option("--release", help="Clear a publication hold")] = False,
    reobserve: Annotated[bool, typer.Option("--reobserve", help="Re-record the newest retained publication receipt against repair findings")] = False,
) -> None:
    """Read-only lightweight startup status, without a network CI wait."""
    from app.services.publication_health import (
        format_publication_health,
        get_project_publication_health,
    )
    from cli.config import get_config_optional

    project_id = get_config_optional().project_id
    if not project_id:
        typer.echo("Manual publication: unknown; no registered project for this directory.")
        if mode is not None:
            raise typer.Exit(2)
        return
    from app.tasks.nightly_publication import (
        publication_hold,
        publication_mode,
        release_publication_hold,
        set_publication_hold,
        set_publication_mode,
    )

    try:
        if mode is not None:
            set_publication_mode(project_id, mode)
        if hold and release:
            raise ValueError("--hold and --release are exclusive")
        if hold:
            full = None
            if through:
                resolved = subprocess.run(["git", "rev-parse", "--verify", f"{through}^{{commit}}"],
                                          capture_output=True, text=True, check=False)
                if resolved.returncode:
                    raise ValueError(f"Unknown commit: {through}")
                full = resolved.stdout.strip()
            set_publication_hold(project_id, through=full, reason=reason)
        elif release:
            release_publication_hold(project_id)
        if reobserve:
            from app.services.publication_health import reobserve_retained_publication

            replay = reobserve_retained_publication(project_id)
            typer.echo("Reobserved: none; no retained publication receipt." if replay is None else
                       f"Reobserved: {replay['state']}; source={str(replay.get('source_commit') or 'unknown')[:12]}; "
                       f"evidence={replay['evidence']}")
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from None
    current = publication_hold(project_id)
    held = ("none" if current is None else f"through {str(current.get('through'))[:12]}" if current.get("through")
            else "all") + (f" ({current.get('reason')})" if current else "")
    typer.echo(f"Publication mode: {publication_mode(project_id)}; hold: {held}")
    try:
        health = get_project_publication_health(project_id)
        typer.echo(format_publication_health(health))
    except Exception:
        typer.echo("Manual publication: unknown; status unavailable. Inspect ST before claiming completion.")


@app.command("publish")
@usage(surface="st.vcs.publish", cmd="st vcs publish [--source ID] [--sha SHA]",
       when="publish now instead of waiting for the hourly push",
       precautions=("defaults: this checkout's project; private repos its head, public repos their newest accepted commit",
                    "never creates commits or touches the checkout; outgoing-secret and workflow-effects checks still apply"),
       tier="reference")
def publish_now(
    source: Annotated[str | None, typer.Option("--source", help="Registered project ID (default: this checkout's project)")] = None,
    sha: Annotated[str | None, typer.Option("--sha", help="Commit to publish, short or full (default: what the hourly push would pick)")] = None,
    now: Annotated[bool, typer.Option("--now", hidden=True, help="Accepted for compatibility; publishing is immediate")] = False,
    authorize_workflow: Annotated[list[str] | None, typer.Option("--authorize-workflow", help="Explicit authority for a listed workflow: exact path for selected source, BASE_SHA:path for a different base workflow; repeat as needed")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Show the complete retained structured observation")] = False,
    with_ack: Annotated[str | None, typer.Option("--with-ack", help="Request id the repo's holder acked yes")] = None,
) -> None:
    """Push one exact committed source and retain the observation."""
    from app.storage.projects import get_project_root_path
    from app.tasks.backup_manual_publish import publish_project_now
    from app.tasks.nightly_publication import publication_hold, select_candidate
    from cli.config import get_config_optional

    source = source or get_config_optional().project_id
    root = get_project_root_path(source) if source else None
    if not source or not root:
        typer.echo("No registered project: run from a project checkout or pass --source.")
        raise typer.Exit(2)
    _coord_guard(Path(root), "publish", with_ack)
    hold = publication_hold(source)
    if sha:
        resolved = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
                                  capture_output=True, text=True, check=False)
        if resolved.returncode:
            typer.echo(f"Unknown commit: {sha}")
            raise typer.Exit(2)
        sha = resolved.stdout.strip()
        # The owner's hold keeps later commits local for every publisher.
        through = (hold or {}).get("through")
        if hold is not None and not (through and subprocess.run(
                ["git", "-C", root, "merge-base", "--is-ancestor", sha, str(through)],
                capture_output=True, check=False).returncode == 0):
            typer.echo(f"Publication is held ({hold.get('reason')})"
                       + (f" through {str(through)[:12]}" if through else "")
                       + "; only the owner releases it: st vcs publication --release")
            raise typer.Exit(2)
    else:
        candidate = select_candidate(source, Path(root), "nightly", hold)
        if candidate["action"] != "publish":
            typer.echo(f"Nothing to publish: {candidate.get('reason')}"
                       + (f" ({candidate['detail']})" if candidate.get("detail") else ""))
            raise typer.Exit(0 if candidate.get("reason") in {"up_to_date", "published"} else 2)
        sha = str(candidate["sha"])
    try:
        result = publish_project_now(source, sha, authorized_workflows=tuple(authorize_workflow or ()))
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from None
    except Exception:
        # Transport/DB errors can contain credentials. Never print raw diagnostics.
        typer.echo("Publication could not establish durable evidence. Inspect canonical publication health before retrying.")
        raise typer.Exit(2) from None
    from app.tasks.backup_publish import _public_evidence

    safe_result = _public_evidence(result)
    complete = bool(result.get("publication_complete") and result.get("evidence_recorded"))
    if json_output:
        output_json(safe_result)
    else:
        details = write_details(Path.cwd(), "publication", json.dumps(safe_result, indent=2, sort_keys=True))
        output_json({"outcome": result.get("status", "completed" if complete else "pending"),
                     "source": sha, "pushed": bool(result.get("pushed")),
                     "blockers": [] if complete else [result.get("reason", "publication_evidence_incomplete")],
                     "unauthorized_workflows": result.get("unauthorized_workflows", []),
                     "evidence": result.get("evidence"), "details": display_path(Path.cwd(), details)})
    if not complete:
        raise typer.Exit(2)

@app.command("nightly")
@usage(surface="st.vcs.nightly", cmd="st vcs nightly --dry-run",
       when="preview or run the hourly publication pass for auto-published projects",
       precautions=("--run publishes immediately", "never commits, changes checkouts or authorizes workflow files"),
       tier="reference")
def nightly(
    dry_run: Annotated[bool, typer.Option("--dry-run/--run", help="Show this hour's selection without side effects")] = True,
    project: Annotated[list[str] | None, typer.Option("--project", help="Limit to project IDs; repeat as needed")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Show complete structured rows")] = False,
) -> None:
    """Select (and with --run, execute) one sequential publication pass."""
    from app.tasks.nightly_publication import run_nightly_publication, summary_line

    result = run_nightly_publication(dry_run=dry_run, project_ids=project or None)
    if json_output:
        output_json(result)
        return
    for row in result.get("projects", []):
        if row.get("reason") != "manual_mode":
            typer.echo(summary_line(row))
    manual = sum(row.get("reason") == "manual_mode" for row in result.get("projects", []))
    typer.echo(f"NIGHTLY:{result['status']}|projects={len(result.get('projects', []))}|manual={manual}")


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
    from ..lib.execution_context import canonical_repo_root

    cwd = Path.cwd().resolve()
    # A worktree of a managed repo audits that repo.
    candidates = [cwd, *([canonical] if (canonical := canonical_repo_root(cwd)) else [])]
    for candidate in candidates:
        for repo in repos:
            if candidate.is_relative_to(repo.resolve()):
                return [repo]
    typer.echo(f"--current needs a managed repository, but {cwd} is not inside one. "
               "Run it from a project checkout, or use --all.", err=True)
    raise typer.Exit(2)


def _parse_worktrees(porcelain: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for block in porcelain.strip().split("\n\n"):
        entry: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            entry[key] = value
        if entry.get("worktree"):
            entries.append(entry)
    return entries


def _worktree_rows(repos: list[Path]) -> list[dict[str, Any]]:
    """Linked worktrees of each repo, with where they live and what work they hold."""
    from ..lib.workspace_paths import get_workspaces_root

    workspaces = get_workspaces_root().resolve()
    rows: list[dict[str, Any]] = []
    for repo in repos:
        if not (repo / ".git").exists():
            continue
        listed = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                                capture_output=True, text=True, check=False)
        if listed.returncode:
            continue
        main, *linked = _parse_worktrees(listed.stdout)
        for entry in linked:
            path = Path(entry["worktree"])
            row: dict[str, Any] = {
                "repo": repo.name, "path": str(path),
                "branch": entry.get("branch", "").removeprefix("refs/heads/") or "detached",
                "outside_workspace": not path.resolve().is_relative_to(workspaces),
                "prunable": "prunable" in entry or not path.is_dir(), "dirty": 0, "unlanded": 0,
            }
            if not row["prunable"]:
                status = subprocess.run(["git", "-C", str(path), "status", "--porcelain"],
                                        capture_output=True, text=True, check=False)
                row["dirty"] = len(status.stdout.splitlines()) if status.returncode == 0 else -1
                if entry.get("HEAD") and main.get("HEAD"):
                    ahead = subprocess.run(["git", "-C", str(repo), "rev-list", "--count",
                                            f"{main['HEAD']}..{entry['HEAD']}"],
                                           capture_output=True, text=True, check=False)
                    row["unlanded"] = int(ahead.stdout.strip() or 0) if ahead.returncode == 0 else -1
            rows.append(row)
    return rows


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
    worktrees: Sequence[dict[str, Any]] = (),
) -> list[VcsIssue]:
    issues: list[VcsIssue] = []
    for tree in worktrees:
        if tree["prunable"]:
            issues.append(VcsIssue(tree["repo"], "worktree", f"missing:{tree['path']}", "git worktree prune"))
        elif tree["outside_workspace"] or tree["dirty"] or tree["unlanded"]:
            where = " outside_workspace" if tree["outside_workspace"] else ""
            issues.append(VcsIssue(
                tree["repo"], "worktree",
                f"{tree['path']} dirty:{tree['dirty']} unlanded:{tree['unlanded']}{where}",
                "land or hand off its work, then git worktree remove",
            ))
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
    worktrees: Sequence[dict[str, Any]] = (),
) -> dict[str, int]:
    cleanup_summary = cleanup_payload["summary"]
    return {
        "worktrees": len(worktrees),
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
    worktrees: Sequence[dict[str, Any]] = (),
) -> str:
    payload = {
        "worktrees": list(worktrees),
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
        f"task_refs={summary['task_refs']} worktrees={summary.get('worktrees', 0)} "
        f"blockers={len(issues)} details:{display_path(Path.cwd(), details)}"
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
    worktrees = _worktree_rows(repos)
    summary = _summary(repos, git_rows, cleanup, unmanaged, task_refs, worktrees)
    issues = _issues(git_rows, cleanup, unmanaged, task_refs, worktrees)
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
            worktrees=worktrees,
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
    """Report Git, cleanup, unmanaged-repo and informal-worktree debt in one compact check."""
    result, issues, details = _run_doctor(all_projects=all_projects, fetch=fetch)
    if ctx.obj.is_compact:
        _print_compact("VCS", result["summary"], issues, details)
    else:
        output_json(result)
    if fail_on_issues and issues:
        raise typer.Exit(2)


def _coord_guard(repo: Path, operation: str, with_ack: str | None) -> None:
    from ..lib import coord

    if not repo.is_dir():
        return
    try:
        coord.guard(repo, operation, with_ack=with_ack)
    except coord.CoordBlocked as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None


def _unheld_repos(repos: list[Path], with_ack: str | None) -> list[Path]:
    """Skip repos another live agent holds or is active in; one line each."""
    from ..lib import coord

    kept: list[Path] = []
    for repo in repos:
        try:
            coord.guard(repo, "reconcile", with_ack=with_ack)
        except coord.CoordBlocked as exc:
            typer.echo(f"skipped: {exc}", err=True)
            continue
        kept.append(repo)
    return kept


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
        "pulls remotes and may delete already-integrated remote task refs; use only when that is intended",
        "use st vcs doctor for local inspection; unpublished local commits are normal, not debt",
        "preserve ownerless work; inspect before cleanup",
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
    with_ack: Annotated[str | None, typer.Option("--with-ack", help="Request id a repo holder acked yes")] = None,
) -> None:
    """Run safe VCS reconciliation: sync, register workspace repos, prune safe residue."""
    initial_repos = _target_repos(all_projects)
    registered = _register_unmanaged(initial_repos) if all_projects else []
    repos = _target_repos(all_projects)
    sync = _sync_repos(_unheld_repos(repos, with_ack))
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
