"""Git hygiene gate and sweep commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext
from ._git_helpers import _get_repo_status
from .cleanup import _iter_target_repos, build_cleanup_status_payload, get_project_id
from .cleanup_display import RepoEntry
from .cleanup_handlers import cleanup_safe_git_residue

app = typer.Typer(
    help=(
        "Enforce git hygiene before and after task work. The gate self-heals "
        "safe residue, then blocks on stashes, orphan branches, dirty trees, "
        "active checkpoints, remote task refs, or non-main branches."
    )
)

_BASE_BRANCH_CANDIDATES = ("main", "master")


@dataclass(frozen=True)
class HygieneIssue:
    """One blocking hygiene issue."""

    project_id: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"project_id": self.project_id, "code": self.code, "detail": self.detail}


def _git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _current_repo_root() -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _target_repos(all_projects: bool, project_id: str | None) -> list[Path]:
    repos = _iter_target_repos(all_projects, project_id)
    if repos or all_projects:
        return repos
    current = _current_repo_root()
    return [current] if current and current.exists() else []


def _base_branch(repo_path: Path) -> str:
    for branch in _BASE_BRANCH_CANDIDATES:
        if _git(repo_path, ["show-ref", "--verify", f"refs/heads/{branch}"]).returncode == 0:
            return branch
    status = _get_repo_status(repo_path)
    return str(status.get("branch") or "main") if status else "main"


def _local_branches(repo_path: Path) -> list[str]:
    result = _git(repo_path, ["branch", "--format=%(refname:short)"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _stash_entries(repo_path: Path) -> list[str]:
    result = _git(repo_path, ["stash", "list", "--format=%gd:%s"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _remote_task_refs(repo_path: Path) -> list[str]:
    result = _git(repo_path, ["for-each-ref", "--format=%(refname:short)", "refs/remotes"])
    if result.returncode != 0:
        return []
    refs: list[str] = []
    for line in result.stdout.splitlines():
        ref = line.strip()
        if not ref or ref.endswith("/HEAD"):
            continue
        _remote, _, branch = ref.partition("/")
        if branch.startswith("task-"):
            refs.append(ref)
    return refs


def _repo_cleanup_entry(payload: dict[str, Any], repo_path: Path) -> RepoEntry | None:
    for repo in payload.get("repositories", []):
        if str(repo.get("path") or "") == str(repo_path):
            return repo
    return None


def _cleanup_issues(repo: RepoEntry) -> list[HygieneIssue]:
    project_id = str(repo["project_id"])
    issues: list[HygieneIssue] = []
    if repo["active_checkpoints"]:
        issues.append(HygieneIssue(project_id, "active_checkpoints", ",".join(repo["checkpoint_task_ids"]) or "present"))
    if repo["dirty_main_repo"] or repo["dirty_checkpoints"]:
        issues.append(HygieneIssue(project_id, "dirty_tree", "uncommitted changes present"))
    if repo["stale_checkpoints"]:
        issues.append(HygieneIssue(project_id, "stale_checkpoints", str(repo["stale_checkpoints"])))
    if repo["snapshot_residue"]:
        issues.append(HygieneIssue(project_id, "snapshot_residue", str(repo["snapshot_residue"])))
    if repo["orphan_task_branches"]:
        detail = ",".join(repo["orphan_branch_names"]) or str(repo["orphan_task_branches"])
        issues.append(HygieneIssue(project_id, "orphan_task_branches", detail))
    if repo["prunable_task_branches"]:
        detail = ",".join(repo["prunable_branch_names"]) or str(repo["prunable_task_branches"])
        issues.append(HygieneIssue(project_id, "prunable_task_branches", detail))
    return issues


def _repo_git_issues(repo_path: Path, *, require_main: bool) -> list[HygieneIssue]:
    status = _get_repo_status(repo_path)
    project_id = repo_path.name
    if status is None:
        return [HygieneIssue(project_id, "not_git_repo", str(repo_path))]

    issues: list[HygieneIssue] = []
    branch = str(status.get("branch") or "")
    base_branch = _base_branch(repo_path)
    if require_main and branch != base_branch:
        issues.append(HygieneIssue(project_id, "not_base_branch", f"{branch or 'HEAD'} != {base_branch}"))
    if int(status.get("uncommitted") or 0):
        issues.append(HygieneIssue(project_id, "uncommitted_changes", str(status.get("uncommitted"))))
    if int(status.get("behind") or 0):
        issues.append(HygieneIssue(project_id, "behind_remote", f"behind:{status.get('behind')}"))
    if int(status.get("ahead") or 0):
        issues.append(HygieneIssue(project_id, "ahead_remote", f"ahead:{status.get('ahead')}"))

    extras = sorted(set(_local_branches(repo_path)) - {base_branch})
    if extras:
        issues.append(HygieneIssue(project_id, "extra_local_branches", ",".join(extras[:8])))

    stashes = _stash_entries(repo_path)
    if stashes:
        issues.append(HygieneIssue(project_id, "stash_entries", ",".join(stashes[:5])))

    remote_refs = _remote_task_refs(repo_path)
    if remote_refs:
        issues.append(HygieneIssue(project_id, "remote_task_refs", ",".join(remote_refs[:8])))
    return issues


def build_hygiene_report(
    *,
    all_projects: bool = False,
    project_id: str | None = None,
    fix: bool = True,
    require_main: bool = True,
) -> dict[str, Any]:
    """Build hygiene report and optionally prune already-safe residue."""
    repos = _target_repos(all_projects, project_id)
    fixed = (0, 0, 0, 0)
    if fix:
        fixed = cleanup_safe_git_residue(repos, dry_run=False)

    payload = build_cleanup_status_payload(all_projects, project_id_override=project_id)
    issues: list[HygieneIssue] = []
    for repo_path in repos:
        repo_entry = _repo_cleanup_entry(payload, repo_path)
        if repo_entry is not None:
            issues.extend(_cleanup_issues(repo_entry))
        issues.extend(_repo_git_issues(repo_path, require_main=require_main))

    return {
        "ok": not issues and payload["summary"]["repos_needing_cleanup"] == 0,
        "issues": [issue.to_dict() for issue in issues],
        "fixed": {
            "registrations": fixed[0],
            "merged_branches": fixed[1],
            "equivalent_branches": fixed[2],
            "closed_branches": fixed[3],
        },
        "cleanup": payload,
    }


def _print_compact(report: dict[str, Any], scope: str) -> None:
    issues = report["issues"]
    fixed = report["fixed"]
    fixed_total = sum(int(fixed[key]) for key in fixed)
    print(f"HYGIENE[{scope}]:ok={int(bool(report['ok']))} issues={len(issues)} fixed={fixed_total}")
    for issue in issues:
        print(f"{issue['project_id']} BLOCK {issue['code']}:{issue['detail']}")


def _detail_parts(detail: str) -> list[str]:
    return [part for part in detail.split(",") if part]


def _filter_closeout_issue(issue: dict[str, str], task_id: str) -> dict[str, str] | None:
    code = issue["code"]
    detail = issue["detail"]
    if code == "active_checkpoints":
        remaining = [part for part in _detail_parts(detail) if part != task_id]
        if not remaining:
            return None
        return {**issue, "detail": ",".join(remaining)}
    if code == "extra_local_branches":
        current_task_branch = f"{task_id}/main"
        remaining = [part for part in _detail_parts(detail) if part != current_task_branch]
        if not remaining:
            return None
        return {**issue, "detail": ",".join(remaining)}
    return issue


def _closeout_blocking_issues(report: dict[str, Any], task_id: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for issue in report["issues"]:
        filtered = _filter_closeout_issue(issue, task_id)
        if filtered is not None:
            issues.append(filtered)
    return issues


def require_hygiene_gate(
    *,
    project_id: str | None = None,
    fix: bool = True,
    require_main: bool = True,
) -> None:
    """Raise typer.Exit when the current project is not safe for task start/closeout."""
    report = build_hygiene_report(project_id=project_id, fix=fix, require_main=require_main)
    if report["ok"]:
        return
    for issue in report["issues"][:10]:
        output_error(f"Hygiene blocked: {issue['project_id']} {issue['code']} {issue['detail']}")
    raise typer.Exit(2)


def require_closeout_hygiene_gate(
    *,
    task_id: str,
    project_id: str | None = None,
    fix: bool = True,
) -> None:
    """Block closeout on unrelated residue while allowing the current task lane."""
    report = build_hygiene_report(project_id=project_id, fix=fix, require_main=False)
    issues = _closeout_blocking_issues(report, task_id)
    if not issues:
        return
    for issue in issues[:10]:
        output_error(f"Closeout hygiene blocked: {issue['project_id']} {issue['code']} {issue['detail']}")
    raise typer.Exit(2)


@app.callback()
def hygiene_callback(ctx: typer.Context) -> None:
    """Initialize context when the hygiene sub-app is invoked directly."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


@app.command("gate")
def hygiene_gate(
    ctx: typer.Context,
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Check all managed projects instead of the current project only."),
    ] = False,
    project_id: Annotated[
        str | None,
        typer.Option("--project", help="Project id to check. Defaults to current project."),
    ] = None,
    fix: Annotated[
        bool,
        typer.Option("--fix/--no-fix", help="Prune already-safe residue before evaluating blockers."),
    ] = True,
    require_main: Annotated[
        bool,
        typer.Option("--require-main/--allow-task-branch", help="Require current branch to be main/master."),
    ] = True,
) -> None:
    """Block unless the target project is clean enough to start or close a code task."""
    resolved_project = get_project_id(all_projects, project_id)
    report = build_hygiene_report(
        all_projects=all_projects,
        project_id=resolved_project,
        fix=fix,
        require_main=require_main,
    )
    if ctx.obj.is_compact:
        _print_compact(report, "all" if all_projects else "current")
    else:
        output_json(report)
    if not report["ok"]:
        raise typer.Exit(2)


@app.command("sweep")
def hygiene_sweep(
    ctx: typer.Context,
    all_projects: Annotated[
        bool,
        typer.Option("--all/--current", help="Sweep all managed projects instead of the current project only."),
    ] = True,
    project_id: Annotated[
        str | None,
        typer.Option("--project", help="Project id to sweep when --all is not used."),
    ] = None,
    fix: Annotated[
        bool,
        typer.Option("--fix/--no-fix", help="Prune already-safe residue before reporting blockers."),
    ] = True,
    fail_on_residue: Annotated[
        bool,
        typer.Option("--fail-on-residue", help="Exit 2 when any blocker remains after the sweep."),
    ] = False,
) -> None:
    """Self-heal safe residue and report remaining blockers."""
    resolved_project = get_project_id(all_projects, project_id)
    report = build_hygiene_report(
        all_projects=all_projects,
        project_id=resolved_project,
        fix=fix,
        require_main=False,
    )
    if ctx.obj.is_compact:
        _print_compact(report, "all" if all_projects else "current")
    else:
        output_json(report)
    if fail_on_residue and not report["ok"]:
        raise typer.Exit(2)
