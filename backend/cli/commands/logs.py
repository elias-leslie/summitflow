"""Log viewing commands using systemd journal.

Provides unified log tailing across SummitFlow and Agent Hub services.
Based on portfolio-ai's journalctl integration pattern.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext
from .logs_config import (
    SYSTEM_SERVICES,
    USER_SERVICES,
    get_service_list,
    validate_since,
)
from .logs_fetcher import fetch_logs, follow_logs, format_logs_compact

app = typer.Typer(help="View and tail service logs")


@app.callback(invoke_without_command=True)
def logs_default(ctx: typer.Context) -> None:
    """View unified logs from SummitFlow and Agent Hub services.

    Without a subcommand, shows the tail of recent logs.
    """
    if ctx.obj is None:
        ctx.obj = OutputContext()
    if ctx.invoked_subcommand is None:
        tail(ctx)


@app.command()
def tail(
    ctx: typer.Context,
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            "-s",
            help="Filter by service (summitflow,agent-hub,redis,postgres,neo4j,all)",
        ),
    ] = None,
    level: Annotated[
        str | None,
        typer.Option(
            "--level",
            "-l",
            help="Filter by level (ERROR,WARN,INFO,DEBUG)",
        ),
    ] = None,
    lines: Annotated[
        int,
        typer.Option(
            "--lines",
            "-n",
            help="Number of lines to show",
        ),
    ] = 100,
    since: Annotated[
        str,
        typer.Option(
            "--since",
            help="Time range (e.g., '30 minutes ago', '1 hour ago', 'today')",
        ),
    ] = "30 minutes ago",
    follow: Annotated[
        bool,
        typer.Option(
            "--follow",
            "-f",
            help="Follow log output (like tail -f)",
        ),
    ] = False,
) -> None:
    """Tail service logs with filtering.

    Examples:
        st logs tail
        st logs tail --service summitflow
        st logs tail -s agent-hub --level ERROR
        st logs tail --since "1 hour ago" --lines 200
        st logs tail -f  # Follow mode
    """
    validated_since = validate_since(since)
    user_svcs, system_svcs = get_service_list(service)

    if follow:
        # Use journalctl --follow directly
        follow_logs(user_svcs, system_svcs, level)
        return

    # Fetch from both user and system services
    all_logs = []

    if user_svcs:
        all_logs.extend(
            fetch_logs(user_svcs, is_user_mode=True, lines=lines, since=validated_since)
        )
    if system_svcs:
        all_logs.extend(
            fetch_logs(system_svcs, is_user_mode=False, lines=lines, since=validated_since)
        )

    # Sort by timestamp
    all_logs.sort(key=lambda x: x.timestamp)

    # Filter by level if specified
    if level:
        level_upper = level.upper()
        all_logs = [log for log in all_logs if log.level == level_upper]

    # Limit to requested number
    all_logs = all_logs[-lines:]

    if not all_logs:
        output_error("No logs found")
        return

    if ctx.obj.is_compact:
        format_logs_compact(all_logs)
    else:
        output_json([log.to_dict() for log in all_logs])


@app.command()
def services(ctx: typer.Context) -> None:
    """List available service names for filtering.

    Examples:
        st logs services
    """
    if ctx.obj.is_compact:
        print("SERVICES:user")
        for name, unit in USER_SERVICES.items():
            print(f"  {name:15} {unit}")
        print("SERVICES:system")
        for name, unit in SYSTEM_SERVICES.items():
            print(f"  {name:15} {unit}")
    else:
        output_json(
            {
                "user_services": USER_SERVICES,
                "system_services": SYSTEM_SERVICES,
            }
        )


@app.command()
def levels(ctx: typer.Context) -> None:
    """Show log level counts from recent logs.

    Examples:
        st logs levels
    """
    user_svcs, system_svcs = get_service_list("all")
    since = "30 minutes ago"
    lines = 1000

    all_logs = []
    if user_svcs:
        all_logs.extend(fetch_logs(user_svcs, is_user_mode=True, lines=lines, since=since))
    if system_svcs:
        all_logs.extend(fetch_logs(system_svcs, is_user_mode=False, lines=lines, since=since))

    # Count by level
    counts: dict[str, int] = {}
    for log in all_logs:
        counts[log.level] = counts.get(log.level, 0) + 1

    if ctx.obj.is_compact:
        total = sum(counts.values())
        print(f"LEVELS:total={total}:since=30m")
        for lvl in ["CRITICAL", "ERROR", "WARN", "INFO", "DEBUG"]:
            count = counts.get(lvl, 0)
            if count > 0:
                print(f"  {lvl:8} {count}")
    else:
        output_json({"counts": counts, "total": len(all_logs), "since": since})
