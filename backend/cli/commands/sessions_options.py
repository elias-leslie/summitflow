"""Typer option aliases for the sessions CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

SessionStatusOption = Annotated[str | None, typer.Option("-s", "--status")]
SessionLimitOption = Annotated[int, typer.Option("--limit")]
SessionAgentOption = Annotated[str | None, typer.Option("--agent")]
ParentSessionOption = Annotated[str | None, typer.Option("--parent-session")]
ProjectOption = Annotated[str | None, typer.Option("--project", "-P")]
ProjectLookupOption = Annotated[
    str | None,
    typer.Option("--project", "-P", help="Project scope for short session ID lookup."),
]
IncludeUnassignedOption = Annotated[
    bool,
    typer.Option(
        "--include-unassigned",
        help="Include imported/unassigned sessions without an agent slug",
    ),
]
RawSessionOption = Annotated[bool, typer.Option("--raw", help="Print full raw session JSON.")]
MonitorTargetArg = Annotated[
    str | None,
    typer.Argument(help="Task ID, session ID/prefix, or empty for active sessions"),
]
MonitorProjectOption = Annotated[str | None, typer.Option("--project", "-P", help="Project scope")]
MonitorStatusOption = Annotated[
    str,
    typer.Option("--status", "-s", help="Session status for overview"),
]
MonitorAgentOption = Annotated[
    str | None,
    typer.Option("--agent", help="Agent slug filter for overview"),
]
MonitorFollowOption = Annotated[
    bool,
    typer.Option("-f", "--follow", help="Follow events in real time"),
]
MonitorLimitOption = Annotated[
    int,
    typer.Option("-n", "--limit", help="Maximum events to show"),
]
MonitorDebugOption = Annotated[
    bool,
    typer.Option("--debug", help="Include debug-level events"),
]
MonitorErrorsOption = Annotated[
    bool,
    typer.Option("--errors", help="Show only error events for a session target"),
]
MonitorHistoryOption = Annotated[
    bool,
    typer.Option("--history", help="Include older linked Agent Hub sessions"),
]
JsonOutputOption = Annotated[bool, typer.Option("--json", help="Output as JSON")]
ReapDryRunOption = Annotated[
    bool,
    typer.Option("--dry-run", help="Preview reapable sessions without closing them"),
]
