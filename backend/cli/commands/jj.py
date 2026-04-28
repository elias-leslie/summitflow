"""st-fronted Jujutsu commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from app.storage.events import log_task_event

from ..lib.jj import (
    LOG_TEMPLATE,
    OP_LOG_TEMPLATE,
    JJError,
    current_git_repo,
    delete_task_bookmark,
    format_status_line,
    is_colocated,
    publish_current_revision,
    run_jj,
    status_summary,
)
from ..output import output_error, output_json
from ..output_context import OutputContext
from ._git_helpers import _get_managed_repos

HELP_TEXT = """Jujutsu workflow through st.

Principles:
  - Agents call st jj or st commit, not raw jj, for normal VCS work.
  - All commands run with --no-pager and non-interactive editor config.
  - Publication runs st check first; jj-backed publish rejects --skip-checks.

Common workflows:
  st jj status
  st jj new -m "start task"
  st jj describe -m "better description"
  st commit -m "fix: concise result" --push --task task-abc
  st jj log --limit 20
  st jj op-log --limit 20
  st jj undo --task task-abc
  st jj op-restore <op-id> --task task-abc
  st jj conflicts
  st jj revert <revision> --message "rollback" --push --task task-abc
"""

app = typer.Typer(help=HELP_TEXT, rich_markup_mode=None)


@app.callback()
def jj_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _repo_or_current(repo: Path | None) -> Path:
    return repo.resolve() if repo else current_git_repo()


def _echo_result(result) -> None:
    typer.echo(result.stdout, nl=not result.stdout.endswith("\n") if result.stdout else True)
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=not result.stderr.endswith("\n"))
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def _run_or_exit(repo: Path, args: list[str]):
    try:
        result = run_jj(repo, args)
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    _echo_result(result)


@app.command()
def status(
    ctx: typer.Context,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path. Defaults to all managed repos.")] = None,
) -> None:
    """Show jj state across managed repos or one repo."""
    repos = [_repo_or_current(repo)] if repo else _get_managed_repos()
    statuses = []
    try:
        statuses = [status_summary(path) for path in repos if path.exists()]
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    if ctx.obj.is_compact:
        print(f"JJ[{len(statuses)}]")
        for item in statuses:
            print(format_status_line(item))
        return
    output_json({"repositories": [item.__dict__ for item in statuses], "total": len(statuses)})


@app.command()
def log(
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Revision count.")] = 20,
) -> None:
    """Show recent jj revisions with stable fields."""
    _run_or_exit(_repo_or_current(repo), ["log", "--no-graph", "-n", str(limit), "-T", LOG_TEMPLATE])


@app.command()
def diff(
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    revision: Annotated[str, typer.Option("--revision", "-r", help="Revision to diff.")] = "@",
) -> None:
    """Show a git-format jj diff."""
    _run_or_exit(_repo_or_current(repo), ["diff", "-r", revision, "--git"])


@app.command()
def show(
    revision: Annotated[str, typer.Argument(help="Revision to show.")] = "@",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Show one revision."""
    _run_or_exit(_repo_or_current(repo), ["show", "-r", revision, "--git"])


@app.command()
def sync(
    ctx: typer.Context,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path. Defaults to all colocated repos.")] = None,
    remote: Annotated[str, typer.Option("--remote", help="Remote name.")] = "origin",
) -> None:
    """Fetch remote jj bookmark state for colocated repos."""
    repos = [_repo_or_current(repo)] if repo else [path for path in _get_managed_repos() if is_colocated(path)]
    results = []
    for path in repos:
        result = run_jj(path, ["git", "fetch", "--remote", remote])
        results.append({
            "repo": path.name,
            "path": str(path),
            "status": "SUCCESS" if result.returncode == 0 else "ERROR",
            "detail": (result.stderr or result.stdout).strip(),
        })
    if ctx.obj.is_compact:
        print(f"JJSYNC[{len(results)}]")
        for item in results:
            print(f"{item['status']}:{item['repo']}:{item['detail'][:120]}")
    else:
        output_json({"repos": results})
    if any(item["status"] == "ERROR" for item in results):
        raise typer.Exit(1)


@app.command("new")
def new_revision(
    message: Annotated[str, typer.Option("--message", "-m", help="Required revision description.")],
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Start a new jj revision with a required description."""
    if not message.strip():
        output_error("description is required")
        raise typer.Exit(2)
    _run_or_exit(_repo_or_current(repo), ["new", "-m", message])


@app.command()
def describe(
    message: Annotated[str, typer.Option("--message", "-m", help="Required revision description.")],
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Describe the current jj revision."""
    if not message.strip():
        output_error("description is required")
        raise typer.Exit(2)
    _run_or_exit(_repo_or_current(repo), ["describe", "-m", message])


@app.command()
def push(
    ctx: typer.Context,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    task_id: Annotated[str, typer.Option("--task", help="Task id for deterministic bookmark and audit log.")] = "",
    bookmark: Annotated[str, typer.Option("--bookmark", help="Explicit bookmark name.")] = "",
    remote: Annotated[str, typer.Option("--remote", help="Remote name.")] = "origin",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show push result without publishing.")] = False,
    delete_bookmark: Annotated[bool, typer.Option("--delete-bookmark", help="Delete the task bookmark locally and remotely.")] = False,
) -> None:
    """Run st check, set a deterministic bookmark, and push current jj revision."""
    path = _repo_or_current(repo)
    try:
        if delete_bookmark:
            result = delete_task_bookmark(path, task_id=task_id, bookmark=bookmark, remote=remote, dry_run=dry_run)
        else:
            result = publish_current_revision(path, task_id=task_id, bookmark=bookmark, remote=remote, dry_run=dry_run)
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    if task_id:
        if delete_bookmark:
            log_task_event(task_id, f"st jj push --delete-bookmark {result['bookmark']} op={result['operation_id']}")
        else:
            log_task_event(task_id, f"st jj push {result['bookmark']} change={result['change_id']} commit={result['commit_id']} op={result['operation_id']}")
    if ctx.obj.is_compact:
        if delete_bookmark:
            print(
                f"JJPUSH:{result['repo']}:{result['status']}:bookmark={result['bookmark']} "
                f"deleted={str(result['deleted']).lower()}"
            )
        else:
            print(
                f"JJPUSH:{result['repo']}:{result['status']}:bookmark={result['bookmark']} "
                f"change={result['change_id']} commit={result['commit_id']} pushed={str(result['pushed']).lower()}"
            )
    else:
        output_json(result)


@app.command()
def undo(
    task_id: Annotated[str, typer.Option("--task", help="Task id for audit log.")] = "",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Undo the last jj operation."""
    path = _repo_or_current(repo)
    _run_or_exit(path, ["undo"])
    if task_id:
        log_task_event(task_id, "st jj undo executed")


@app.command("op-log")
def op_log(
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Operation count.")] = 20,
) -> None:
    """Show recent jj operations."""
    _run_or_exit(_repo_or_current(repo), ["op", "log", "--no-graph", "-n", str(limit), "-T", OP_LOG_TEMPLATE])


@app.command("op-restore")
def op_restore(
    operation_id: Annotated[str, typer.Argument(help="Operation id to restore.")],
    task_id: Annotated[str, typer.Option("--task", help="Task id for audit log.")] = "",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Restore repo state to a previous jj operation."""
    path = _repo_or_current(repo)
    _run_or_exit(path, ["op", "restore", operation_id])
    if task_id:
        log_task_event(task_id, f"st jj op-restore {operation_id} executed")


@app.command()
def recover(
    to: Annotated[str | None, typer.Option("--to", help="Operation id to restore non-interactively.")] = None,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Show operation log, or restore to --to."""
    path = _repo_or_current(repo)
    if to:
        _run_or_exit(path, ["op", "restore", to])
    else:
        _run_or_exit(path, ["op", "log", "--no-graph", "-n", "20", "-T", OP_LOG_TEMPLATE])


@app.command()
def abandon(
    revision: Annotated[str, typer.Argument(help="Revision to abandon.")] = "@",
    task_id: Annotated[str, typer.Option("--task", help="Task id for audit log.")] = "",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Abandon a local jj revision; recover with st jj undo/op-restore."""
    path = _repo_or_current(repo)
    _run_or_exit(path, ["abandon", revision])
    if task_id:
        log_task_event(task_id, f"st jj abandon {revision} executed")


@app.command()
def restore(
    paths: Annotated[list[str] | None, typer.Argument(help="Optional paths to restore.")] = None,
    from_revision: Annotated[str | None, typer.Option("--from", "-f", help="Source revision.")] = None,
    into_revision: Annotated[str | None, typer.Option("--into", "-t", help="Destination revision.")] = None,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Restore paths without invoking an interactive diff editor."""
    args = ["restore"]
    if from_revision:
        args.extend(["--from", from_revision])
    if into_revision:
        args.extend(["--into", into_revision])
    args.extend(paths or [])
    _run_or_exit(_repo_or_current(repo), args)


@app.command()
def conflicts(
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """List conflicted paths."""
    path = _repo_or_current(repo)
    try:
        result = run_jj(path, ["resolve", "--list"])
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    detail = (result.stderr or result.stdout).strip()
    if result.returncode != 0 and "No conflicts found" in detail:
        print("CONFLICTS[0]")
        return
    _echo_result(result)


@app.command()
def revert(
    revision: Annotated[str, typer.Argument(help="Published revision to revert with a new change.")],
    message: Annotated[str, typer.Option("--message", "-m", help="Optional rollback description.")] = "",
    onto: Annotated[str, typer.Option("--onto", help="Revision to apply the revert onto.")] = "@",
    push: Annotated[bool, typer.Option("--push/--no-push", help="Publish the rollback after st check.")] = False,
    task_id: Annotated[str, typer.Option("--task", help="Task id for bookmark and audit log.")] = "",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Revert already-pushed work by creating a new rollback change."""
    path = _repo_or_current(repo)
    _run_or_exit(path, ["revert", "-r", revision, "--onto", onto])
    if message.strip():
        _run_or_exit(path, ["describe", "-m", message])
    if task_id:
        log_task_event(task_id, f"st jj revert {revision} onto={onto} executed")
    if not push:
        return
    try:
        result = publish_current_revision(path, task_id=task_id)
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    if task_id:
        log_task_event(
            task_id,
            f"st jj revert push {result['bookmark']} change={result['change_id']} "
            f"commit={result['commit_id']} op={result['operation_id']}",
        )
    print(
        f"JJREVERT:{result['repo']}:{result['status']}:bookmark={result['bookmark']} "
        f"change={result['change_id']} commit={result['commit_id']} pushed={str(result['pushed']).lower()}"
    )
