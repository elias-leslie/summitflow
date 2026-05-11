"""st-fronted Jujutsu commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from app.storage.events import log_task_event

from ..details import display_path, summary_hint, write_details
from ..lib.jj import (
    LOG_TEMPLATE,
    OP_LOG_TEMPLATE,
    JJError,
    current_git_repo,
    delete_task_bookmark,
    format_status_line,
    init_colocated,
    is_colocated,
    publish_current_revision,
    run_git,
    run_jj,
    status_summary,
)
from ..output import output_error, output_json
from ._git_helpers import _get_managed_repos
from .cleanup_handlers import cleanup_safe_git_residue

HELP_TEXT = (
    "Jujutsu workflow through st.\n\n"
    "Principles:\n"
    "  - Use st vcs doctor/reconcile for cross-repo hygiene.\n"
    "  - Agents call st jj or st commit, not raw jj.\n"
    "  - All commands run with --no-pager and non-interactive editor config.\n\n"
    "Common workflows:\n"
    "  st jj status | init --repo /path | new -m \"msg\" | describe -m \"msg\"\n"
    "  st commit -m \"fix\" --push --task task-abc\n"
    "  st jj push --bookmark main --revision main\n"
    "  st jj log --limit 20 | op-log --limit 20 | remote-bookmarks <name>\n"
    "  st jj undo --task task-abc | op-restore <op-id> --task task-abc\n"
    "  st jj conflicts | revert <rev> --message \"rollback\" --push --task task-abc"
)

app = typer.Typer(help=HELP_TEXT, rich_markup_mode=None)


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


def _git_revision(revision: str) -> str:
    return "HEAD" if revision == "@" else revision


def _write_jj_result(repo: Path, name: str, result, label: str) -> None:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    details = write_details(repo, name, output)
    line_count = len(output.splitlines())
    print(
        f"{label}:{'OK' if result.returncode == 0 else 'FAIL'}:{result.returncode}|"
        f"lines={line_count}|details:{display_path(repo, details)}|hint:{summary_hint(output)}"
    )
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def _log_and_run(repo: Path, args: list[str], task_id: str, msg: str) -> None:
    _run_or_exit(repo, args)
    if task_id:
        log_task_event(task_id, msg)


def _prune_residue(path: Path, result: dict) -> None:
    if not result.get("pushed"):
        return
    try:
        counts = cleanup_safe_git_residue([path], dry_run=False)
    except Exception:
        counts = (0, 0, 0, 0, 0, 0)
    result["residue_pruned"] = sum(counts)


def _push_log(task_id: str, result: dict, delete_bookmark: bool) -> None:
    if delete_bookmark:
        log_task_event(task_id, f"st jj push --delete-bookmark {result['bookmark']} op={result['operation_id']}")
    else:
        log_task_event(
            task_id,
            f"st jj push {result['bookmark']} change={result['change_id']} commit={result['commit_id']} op={result['operation_id']}",
        )


def _push_compact(result: dict, delete_bookmark: bool) -> None:
    if delete_bookmark:
        print(f"JJPUSH:{result['repo']}:{result['status']}:bookmark={result['bookmark']} deleted={str(result['deleted']).lower()}")
    else:
        print(f"JJPUSH:{result['repo']}:{result['status']}:bookmark={result['bookmark']} change={result['change_id']} commit={result['commit_id']} pushed={str(result['pushed']).lower()}")


def _revert_publish(path: Path, task_id: str) -> None:
    try:
        result = publish_current_revision(path, task_id=task_id)
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    if task_id:
        log_task_event(
            task_id,
            f"st jj revert push {result['bookmark']} change={result['change_id']} commit={result['commit_id']} op={result['operation_id']}",
        )
    print(f"JJREVERT:{result['repo']}:{result['status']}:bookmark={result['bookmark']} change={result['change_id']} commit={result['commit_id']} pushed={str(result['pushed']).lower()}")


@app.command()
def init(
    ctx: typer.Context,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    all_repos: Annotated[bool, typer.Option("--all", help="Initialize every managed repo missing jj colocation.")] = False,
) -> None:
    """Initialize jj colocation for clean Git repositories."""
    if repo and all_repos:
        output_error("choose either --repo or --all")
        raise typer.Exit(2)
    repos = _get_managed_repos() if all_repos else [_repo_or_current(repo)]
    results = []
    try:
        for path in repos:
            results.append(init_colocated(path))
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    if ctx.obj.is_compact:
        print(f"JJINIT[{len(results)}]")
        for item in results:
            detail = item.get("reason") or f"state={item.get('state', '-')}"
            print(f"{item['status']}:{item['repo']}:{detail}")
        return
    output_json({"repos": results})


@app.command()
def status(
    ctx: typer.Context,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path. Defaults to all managed repos.")] = None,
) -> None:
    """Show jj state across managed repos or one repo."""
    repos = [_repo_or_current(repo)] if repo else _get_managed_repos()
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
    path = _repo_or_current(repo)
    if is_colocated(path):
        _run_or_exit(path, ["log", "--no-graph", "-n", str(limit), "-T", LOG_TEMPLATE])
        return
    result = run_git(path, ["log", f"-n{limit}", "--date=iso", "--format=%h\t%H\t%ae\t%ci\t%s"])
    _echo_result(result)


@app.command()
def diff(
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    revision: Annotated[str, typer.Option("--revision", "-r", help="Revision to diff.")] = "@",
    stdout: Annotated[bool, typer.Option("--stdout", help="Print raw diff instead of details path.")] = False,
) -> None:
    """Show a git-format diff for jj or plain Git repositories."""
    path = _repo_or_current(repo)
    if not is_colocated(path):
        result = run_git(path, ["diff", _git_revision(revision), "--"])
        if stdout:
            _echo_result(result)
            return
        _write_jj_result(path, "git-diff", result, f"GITDIFF:rev={_git_revision(revision)}")
        return
    if stdout:
        _run_or_exit(path, ["diff", "-r", revision, "--git"])
        return
    result = run_jj(path, ["diff", "-r", revision, "--git"])
    _write_jj_result(path, "jj-diff", result, f"JJDIFF:rev={revision}")


@app.command()
def show(
    revision: Annotated[str, typer.Argument(help="Revision to show.")] = "@",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    stdout: Annotated[bool, typer.Option("--stdout", help="Print raw revision patch instead of details path.")] = False,
) -> None:
    """Show one revision for jj or plain Git repositories."""
    path = _repo_or_current(repo)
    if not is_colocated(path):
        result = run_git(path, ["show", _git_revision(revision)])
        if stdout:
            _echo_result(result)
            return
        _write_jj_result(path, "git-show", result, f"GITSHOW:rev={_git_revision(revision)}")
        return
    if stdout:
        _run_or_exit(path, ["show", "-r", revision, "--git"])
        return
    result = run_jj(path, ["show", "-r", revision, "--git"])
    _write_jj_result(path, "jj-show", result, f"JJSHOW:rev={revision}")


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


@app.command("remote-bookmarks")
def remote_bookmarks(
    names: Annotated[list[str] | None, typer.Argument(help="Optional bookmark names or patterns.")] = None,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
    remote: Annotated[str, typer.Option("--remote", help="Remote name.")] = "origin",
    fetch: Annotated[bool, typer.Option("--fetch/--no-fetch", help="Fetch before listing.")] = False,
) -> None:
    """List remote bookmarks through the st jj surface."""
    path = _repo_or_current(repo)
    if fetch:
        _run_or_exit(path, ["git", "fetch", "--remote", remote])
    _run_or_exit(path, ["bookmark", "list", "--remote", remote, *(names or [])])


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
    revision: Annotated[str, typer.Option("--revision", "-r", help="Revision to publish.")] = "@",
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
            result = publish_current_revision(
                path,
                task_id=task_id,
                bookmark=bookmark,
                revision=revision,
                remote=remote,
                dry_run=dry_run,
            )
            _prune_residue(path, result)
    except JJError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    if task_id:
        _push_log(task_id, result, delete_bookmark)
    if ctx.obj.is_compact:
        _push_compact(result, delete_bookmark)
    else:
        output_json(result)


@app.command()
def undo(
    task_id: Annotated[str, typer.Option("--task", help="Task id for audit log.")] = "",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Undo the last jj operation."""
    _log_and_run(_repo_or_current(repo), ["undo"], task_id, "st jj undo executed")


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
    _log_and_run(_repo_or_current(repo), ["op", "restore", operation_id], task_id, f"st jj op-restore {operation_id} executed")


@app.command()
def recover(
    to: Annotated[str | None, typer.Option("--to", help="Operation id to restore non-interactively.")] = None,
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Show operation log, or restore to --to."""
    path = _repo_or_current(repo)
    _run_or_exit(path, ["op", "restore", to] if to else ["op", "log", "--no-graph", "-n", "20", "-T", OP_LOG_TEMPLATE])


@app.command()
def abandon(
    revision: Annotated[str, typer.Argument(help="Revision to abandon.")] = "@",
    task_id: Annotated[str, typer.Option("--task", help="Task id for audit log.")] = "",
    repo: Annotated[Path | None, typer.Option("--repo", "-R", help="Repository path.")] = None,
) -> None:
    """Abandon a local jj revision; recover with st jj undo/op-restore."""
    _log_and_run(_repo_or_current(repo), ["abandon", revision], task_id, f"st jj abandon {revision} executed")


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
    if push:
        _revert_publish(path, task_id)
