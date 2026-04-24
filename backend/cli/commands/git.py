"""Git management commands for the CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Annotated, Any

import typer

from .._client_base import APIError
from ..client import STClient
from ..output import output_error, output_json
from ..output_context import OutputContext
from ._git_helpers import (
    _format_compact_repo,
    _get_managed_repos,
    _get_repo_status,
    _print_sync_compact,
    _sync_repo,
)

app = typer.Typer(help="Git repository management")


@app.callback()
def git_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


@app.command()
def status(
    ctx: typer.Context,
    _all_repos: Annotated[bool, typer.Option("--all", "-a", help="Show all known managed repos")] = True,
    short: Annotated[bool, typer.Option("--short", help="Alias for compact status output")] = False,
) -> None:
    """Show git status for managed repositories.

    Displays status in TOON format when --compact is used:
    GIT[N]
    <name> <branch> <state> uncommitted:N ahead:N behind:N

    Examples:
        st git status
        st git status --short
        st --compact git status
    """
    repos: list[dict[str, Any]] = [s for p in _get_managed_repos() if (s := _get_repo_status(p))]
    if short or ctx.obj.is_compact:
        print(f"GIT[{len(repos)}]")
        for repo in repos:
            print(_format_compact_repo(repo))
    else:
        output_json({"repositories": repos, "total": len(repos)})


@app.command()
def sync(
    ctx: typer.Context,
    _pull_only: Annotated[bool, typer.Option("--pull-only", help="Only pull, don't push (default)")] = True,
) -> None:
    """Sync all managed repositories by pulling from remote.

    This pulls changes without creating commits. Use for keeping local repos
    up to date with remote. Will not sync repos with uncommitted changes.

    Examples:
        st git sync
        st --compact git sync
    """
    results = [_sync_repo(p, s) for p in _get_managed_repos() if (s := _get_repo_status(p))]
    if ctx.obj.is_compact:
        _print_sync_compact(results)
    else:
        output_json({"results": results, "total": len(results)})


@app.command("commit", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def commit(ctx: typer.Context) -> None:
    """Run the managed commit workflow.

    Examples:
        st git commit --current --push --task task-abc --msg "..."
        st git commit --sync-only
    """
    raise typer.Exit(_commit_main(list(ctx.args)))


def _commit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="st git commit")
    parser.add_argument("--current", action="store_true", default=True)
    parser.add_argument("--all", dest="all_repos", action="store_true")
    parser.add_argument("--push", action="store_true", default=True)
    parser.add_argument("--no-push", dest="push", action="store_false")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-checks", "--skip-tests", dest="skip_checks", action="store_true")
    parser.add_argument("--msg", default="")
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sync-only", action="store_true")
    parser.add_argument("--task", default="")
    return parser


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def _current_repo() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        output_error("Not inside a git repository")
        raise typer.Exit(1) from None
    return Path(result.stdout.strip())


def _target_repos(all_repos: bool) -> list[Path]:
    return _get_managed_repos() if all_repos else [_current_repo()]


def _dirty(repo: Path, paths: list[str] | None = None) -> bool:
    args = ["status", "--porcelain"]
    if paths:
        args.extend(["--", *paths])
    return bool(_git(repo, args).stdout.strip())


def _path_in_scope(path: str, scopes: list[str]) -> bool:
    normalized = Path(path).as_posix()
    return any(normalized == scope or normalized.startswith(f"{scope.rstrip('/')}/") for scope in scopes)


def _staged_outside_scope(repo: Path, scopes: list[str]) -> list[str]:
    if not scopes:
        return []
    staged = _git(repo, ["diff", "--cached", "--name-only"]).stdout.strip().splitlines()
    return [path for path in staged if path and not _path_in_scope(path, scopes)]


def _branch(repo: Path) -> str:
    return _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "HEAD"


def _push_args(repo: Path, *, force: bool) -> list[str]:
    args = ["push"]
    if force:
        args.append("--force-with-lease")
    upstream = _git(repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    branch = _branch(repo)
    if upstream.returncode != 0 and branch not in {"HEAD", "main", "master"}:
        args.extend(["--set-upstream", "origin", branch])
    return args


def _run_checks(repo: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["st", "check", "--quick", "--changed-only"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    detail = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, detail[-1200:]


def _default_message(repo: Path, task_id: str) -> str:
    staged = _git(repo, ["diff", "--cached", "--name-only"]).stdout.strip().splitlines()
    count = len([line for line in staged if line.strip()])
    prefix = f"autocode({task_id})" if task_id else "chore"
    return f"{prefix}: update {repo.name} ({count} file{'s' if count != 1 else ''})"


def _commit_repo(repo: Path, opts: argparse.Namespace) -> dict[str, str | bool]:
    result: dict[str, str | bool] = {"repo": repo.name, "path": str(repo), "status": "SKIP", "pushed": False}
    scope_paths = [str(Path(path)) for path in opts.path] if opts.path else []
    outside_staged = _staged_outside_scope(repo, scope_paths)
    if outside_staged:
        return {
            **result,
            "status": "BLOCKED",
            "reason": "staged_changes_outside_scope",
            "detail": "\n".join(outside_staged[:20]),
        }
    if not _dirty(repo, scope_paths or None):
        if opts.push:
            push = _git(repo, _push_args(repo, force=opts.force))
            if push.returncode != 0:
                return {**result, "status": "ERROR", "reason": push.stderr.strip()}
            return {**result, "status": "SKIP", "reason": "clean", "pushed": True}
        return {**result, "reason": "clean"}
    if not opts.skip_checks:
        ok, detail = _run_checks(repo)
        if not ok:
            return {**result, "status": "BLOCKED", "reason": "quality_gates_failed", "detail": detail}
    add_args = ["add", "-A"]
    if scope_paths:
        add_args.extend(["--", *scope_paths])
    add = _git(repo, add_args)
    if add.returncode != 0:
        return {**result, "status": "ERROR", "reason": add.stderr.strip()}
    if not _git(repo, ["diff", "--cached", "--quiet"]).returncode:
        return {**result, "reason": "no_staged_changes"}
    message = opts.msg or _default_message(repo, opts.task)
    commit_result = _git(repo, ["commit", "-m", message])
    if commit_result.returncode != 0:
        return {**result, "status": "ERROR", "reason": commit_result.stderr.strip()}
    sha = _git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip()
    result.update({"status": "SUCCESS", "sha": sha, "message": message})
    if opts.push:
        push = _git(repo, _push_args(repo, force=opts.force))
        if push.returncode != 0:
            return {**result, "status": "ERROR", "reason": push.stderr.strip()}
        result["pushed"] = True
    return result


def _sync_only(repos: list[Path], json_output: bool) -> int:
    results = []
    for repo in repos:
        status = _get_repo_status(repo)
        if not status:
            continue
        results.append(_sync_repo(repo, status))
    if json_output:
        print(json.dumps({"repos": results}, indent=2, sort_keys=True))
    else:
        _print_sync_compact(results)
    return 1 if any(item.get("status") == "failed" for item in results) else 0


def _commit_main(argv: list[str]) -> int:
    parser = _commit_parser()
    try:
        opts = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    repos = _target_repos(bool(opts.all_repos))
    if opts.sync_only:
        return _sync_only(repos, bool(opts.json))
    results = [_commit_repo(repo, opts) for repo in repos if repo.exists()]
    if opts.json:
        print(json.dumps({"repos": results}, indent=2, sort_keys=True))
    else:
        ok = sum(1 for item in results if item.get("status") == "SUCCESS")
        skip = sum(1 for item in results if item.get("status") == "SKIP")
        blocked = sum(1 for item in results if item.get("status") == "BLOCKED")
        err = sum(1 for item in results if item.get("status") == "ERROR")
        for item in results:
            status = item.get("status")
            repo = item.get("repo")
            detail = item.get("sha") or item.get("reason") or ""
            print(f"  {status}:{repo}:{detail}:pushed={str(item.get('pushed', False)).lower()}")
        print(f"\nCOMMIT[{len(results)}]:ok={ok}|skip={skip}|err={err}|blocked={blocked}:{'SUCCESS' if not err and not blocked else 'BLOCKED'}")
    return 1 if any(item.get("status") in {"ERROR", "BLOCKED"} for item in results) else 0


@app.command("finalize-task")
def finalize_task(task_id: str) -> None:
    """Finalize merge/cleanup for a completed or conflicted residue task checkpoint."""
    client = STClient(require_project=False)
    try:
        result = client.finalize_task_merge(task_id)
    except APIError as e:
        output_error(f"Failed to finalize task merge: {e.detail}")
        raise typer.Exit(1) from None
    output_json(result)


@app.command("resolve-conflict")
def resolve_conflict(task_id: str) -> None:
    """Reopen a residue task for conflict-resolution autocode in its shared task checkout."""
    client = STClient(require_project=False)
    try:
        result = client.resolve_task_conflict(task_id)
    except APIError as e:
        output_error(f"Failed to prepare conflict resolution: {e.detail}")
        raise typer.Exit(1) from None
    output_json(result)


@app.command("smart-sync")
def smart_sync(project_id: str) -> None:
    """Run Smart Sync for one managed project."""
    client = STClient(require_project=False)
    try:
        result = client.smart_sync_project(project_id)
    except APIError as e:
        output_error(f"Failed to smart sync project: {e.detail}")
        raise typer.Exit(1) from None
    output_json(result)
