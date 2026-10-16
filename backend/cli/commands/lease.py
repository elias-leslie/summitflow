"""File-level lease coordination for parallel agents.

The lease primitive replaces per-task branches as the coordination mechanism.
Leases are advisory: the edit hook warns on another agent's file lease and
records every writer; st commit refuses to sweep another session's writes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from ..config import get_config_optional
from ..lib import coord
from ..lib.leases import (
    acquire,
    acquire_mark,
    check,
    format_pulse_line,
    heartbeat,
    list_active,
    release,
    repo_marks,
    take,
)
from ..lib.usage import usage
from ..output import output_error, output_success

app = typer.Typer(help="File-level lease coordination across parallel agents")


def _resolve_project() -> tuple[str, str | None]:
    """Project id plus the root relative paths resolve against: the current checkout of that project."""
    cfg = get_config_optional()
    pid = cfg.project_id if cfg else ""
    if not pid:
        output_error("No project detected. Run inside a registered project or set ST_PROJECT_ID.")
        raise typer.Exit(2)
    here = coord.project_for_path(Path.cwd())
    if here is not None and here[0] == pid:
        return pid, str(here[1])
    return pid, cfg.project_root if cfg else None


@app.command(name="lease")
@usage(
    surface="st.lease",
    cmd="st lease '<glob>...' | --hold '<purpose>' | --list [--all] | --release | --take <path>",
    when="declare sweep scope before refactor; --hold a repo for integration; release on completion",
    precautions=(
        "the edit hook auto-leases each edited file and warns on another agent's lease; own st commit releases committed paths",
        "relative globs resolve against the current checkout at acquire time",
        "stale leases auto-release after 30min idle",
    ),
    tier="reference",
)
def lease_command(
    globs: Annotated[
        list[str] | None,
        typer.Argument(help="Glob patterns to lease (e.g. 'app/api/**')"),
    ] = None,
    check_path: Annotated[
        str | None,
        typer.Option("--check", help="Check if a path is held by another agent. Exit 0 free, 2 held."),
    ] = None,
    list_flag: Annotated[
        bool,
        typer.Option("--list", help="List active leases for current project"),
    ] = False,
    take_path: Annotated[
        str | None,
        typer.Option("--take", help="Forcibly claim a path from another holder"),
    ] = None,
    release_glob: Annotated[
        str | None,
        typer.Option("--release", help="Release one glob or lease id (or use --release-all)"),
    ] = None,
    release_all: Annotated[
        bool,
        typer.Option("--release-all", help="Release all of current agent's leases"),
    ] = False,
    heartbeat_flag: Annotated[
        bool,
        typer.Option("--heartbeat", help="Touch all current agent's leases"),
    ] = False,
    task_id: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Associate lease with a task id"),
    ] = None,
    hold: Annotated[
        str | None,
        typer.Option("--hold", help="Hold the whole repo with a coarse purpose (e.g. integration); others' commit/publish/rebuild need your ack"),
    ] = None,
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="With --list: every project on this host"),
    ] = False,
) -> None:
    """File-level lease for parallel-agent coordination."""
    if list_flag and all_projects:
        for line in coord.system_lines():
            print(line)
        return
    pid, project_root = _resolve_project()

    if hold:
        lease = acquire_mark(pid, project_root or ".", "hold", hold)
        output_success(f"Holding {pid} ({lease.purpose}) as {lease.agent_id}; release: st lease --release-all")
        return

    if list_flag:
        leases = list_active(pid)
        if not leases:
            print("No active leases.")
            return
        for lease in leases:
            print(format_pulse_line(lease))
        for mark in repo_marks(pid):
            print(coord.holder_line(pid, mark))
        return

    if check_path:
        ok, holder = check(pid, check_path, project_root=project_root)
        if ok:
            return
        assert holder is not None
        print(
            f"BLOCKED: {check_path} held by {holder.agent_id} "
            f"(acquired {holder.acquired_at}, task={holder.task_id or '--'})",
            file=sys.stderr,
        )
        raise typer.Exit(2)

    if take_path:
        lease = take(pid, take_path, project_root=project_root)
        output_success(f"Took over {take_path}. lease_id={lease.lease_id}")
        return

    if release_all or release_glob is not None:
        n = release(pid, release_glob if not release_all else None, project_root=project_root)
        output_success(f"Released {n} lease(s).")
        return

    if heartbeat_flag:
        n = heartbeat(pid)
        output_success(f"Touched {n} lease(s).")
        return

    if not globs:
        output_error(
            "Provide globs to acquire, or use --list / --check / --take / --release."
        )
        raise typer.Exit(2)
    lease = acquire(pid, list(globs), task_id=task_id, project_root=project_root)
    output_success(f"Acquired lease {lease.lease_id} on: {', '.join(lease.globs)}")

