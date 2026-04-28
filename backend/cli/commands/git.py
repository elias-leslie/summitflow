"""Git read/repair commands for the CLI."""

from __future__ import annotations

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

app = typer.Typer(
    help=("Git inspection and residue repair. Use st commit for commits and st jj for normal VCS work.")
)


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
