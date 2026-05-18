"""File-level lease coordination for parallel agents.

The lease primitive replaces per-task branches as the coordination mechanism.
Edit-time gate: agents check before touching a file held by another agent's
lease. Commit-time has no gate.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from ..config import get_config_optional
from ..lib.leases import (
    acquire,
    check,
    format_pulse_line,
    heartbeat,
    list_active,
    release,
    take,
    wait,
)
from ..lib.usage import usage
from ..output import output_error, output_success

app = typer.Typer(help="File-level lease coordination across parallel agents")


def _resolve_project_id() -> str:
    cfg = get_config_optional()
    pid = cfg.project_id if cfg else ""
    if not pid:
        output_error("No project detected. Run inside a registered project or set ST_PROJECT_ID.")
        raise typer.Exit(2)
    return pid


@app.command(name="lease")
@usage(
    surface="st.lease",
    cmd="st lease '<glob>...' | --check <path> | --list | --release | --take <path> | --wait <path>",
    when="declare sweep scope before refactor; check before edit; release on completion",
    precautions=(
        "implicit acquire happens on Edit/Write via the PreToolUse hook",
        "stale leases auto-release after 30min idle",
        "--check exits 2 when another agent holds the path",
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
    wait_path: Annotated[
        str | None,
        typer.Option("--wait", help="Block until path is released"),
    ] = None,
    release_glob: Annotated[
        str | None,
        typer.Option("--release", help="Release a specific glob (or use --release-all)"),
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
) -> None:
    """File-level lease for parallel-agent coordination."""
    pid = _resolve_project_id()

    if list_flag:
        leases = list_active(pid)
        if not leases:
            print("No active leases.")
            return
        for lease in leases:
            print(format_pulse_line(lease))
        return

    if check_path:
        ok, holder = check(pid, check_path)
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
        lease = take(pid, take_path)
        output_success(f"Took over {take_path}. lease_id={lease.lease_id}")
        return

    if wait_path:
        if wait(pid, wait_path):
            output_success(f"{wait_path} is now free.")
            return
        output_error(f"Timeout waiting for {wait_path}.")
        raise typer.Exit(1)

    if release_all or release_glob is not None:
        n = release(pid, release_glob if not release_all else None)
        output_success(f"Released {n} lease(s).")
        return

    if heartbeat_flag:
        n = heartbeat(pid)
        output_success(f"Touched {n} lease(s).")
        return

    if not globs:
        output_error(
            "Provide globs to acquire, or use --list / --check / --take / --wait / --release."
        )
        raise typer.Exit(2)
    lease = acquire(pid, list(globs), task_id=task_id)
    output_success(f"Acquired lease {lease.lease_id} on: {', '.join(lease.globs)}")
