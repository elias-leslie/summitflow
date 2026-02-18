"""Feedback commands for the CLI - agent feedback on infrastructure components."""

from __future__ import annotations

from typing import Annotated

import typer

from .feedback_commands import (
    get_impl,
    list_impl,
    report_impl,
    resolve_impl,
    search_impl,
    summary_impl,
    vote_impl,
)

app = typer.Typer(
    name="feedback",
    help="Agent feedback system: report friction, ideas, improvements, and praise.",
    no_args_is_help=True,
)


@app.command("report")
def report(
    component_id: Annotated[str, typer.Argument(help="Component ID (e.g. sf.cli, ah.memory)")],
    title: Annotated[str, typer.Argument(help="Short descriptive title")],
    feedback_type: Annotated[
        str, typer.Option("--type", "-t", help="Type: friction, idea, improvement, praise")
    ] = "friction",
    severity: Annotated[
        str | None, typer.Option("--severity", "-s", help="Severity: low, medium, high (friction only)")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--desc", "-d", help="Detailed description")
    ] = None,
    project_id: Annotated[
        str, typer.Option("--project", "-p", help="Project ID")
    ] = "summitflow",
    session_id: Annotated[
        str | None, typer.Option("--session", help="Session ID of the reporter")
    ] = None,
    agent_slug: Annotated[
        str | None, typer.Option("--agent", help="Agent slug")
    ] = None,
    model_used: Annotated[
        str | None, typer.Option("--model", help="Model used")
    ] = None,
    session_type: Annotated[
        str | None, typer.Option("--session-type", help="Session type")
    ] = None,
    auto_dedup: Annotated[
        bool, typer.Option("--auto-dedup", help="Auto-vote on similar existing instead of creating new")
    ] = False,
) -> None:
    """Report new feedback on a component.

    Examples:
      st feedback report sf.cli "Error message unhelpful" --type friction --severity medium
      st feedback report ah.memory "Pre-load cross-project context" --type idea
      st feedback report sf.worktree "Isolation worked perfectly" --type praise
      st feedback report sf.dt "Cache ruff results for unchanged files" --type improvement
    """
    report_impl(
        component_id,
        title,
        feedback_type=feedback_type,
        severity=severity,
        description=description,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        model_used=model_used,
        session_type=session_type,
        auto_dedup=auto_dedup,
    )


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    component_id: Annotated[
        str | None, typer.Option("--component", "-c", help="Filter by component")
    ] = None,
    feedback_type: Annotated[
        str | None, typer.Option("--type", "-t", help="Filter by type")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter by status")
    ] = None,
    project_id: Annotated[
        str | None, typer.Option("--project", "-p", help="Filter by project")
    ] = None,
    sort: Annotated[
        str, typer.Option("--sort", help="Sort: votes, newest, oldest")
    ] = "votes",
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 20,
) -> None:
    """Search feedback items by keyword.

    Examples:
      st feedback search "memory injection"
      st feedback search "error" --component sf.cli --type friction
    """
    search_impl(
        query,
        component_id=component_id,
        feedback_type=feedback_type,
        status=status,
        project_id=project_id,
        sort=sort,
        limit=limit,
    )


@app.command("list")
def list_feedback(
    component_id: Annotated[
        str | None, typer.Option("--component", "-c", help="Filter by component")
    ] = None,
    feedback_type: Annotated[
        str | None, typer.Option("--type", "-t", help="Filter by type")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter by status")
    ] = None,
    project_id: Annotated[
        str | None, typer.Option("--project", "-p", help="Filter by project")
    ] = None,
    sort: Annotated[
        str, typer.Option("--sort", help="Sort: votes, newest, oldest")
    ] = "votes",
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 50,
) -> None:
    """List feedback items with filters.

    Examples:
      st feedback list
      st feedback list --component ah.memory --type idea
      st feedback list --sort votes --status open
    """
    list_impl(
        component_id=component_id,
        feedback_type=feedback_type,
        status=status,
        project_id=project_id,
        sort=sort,
        limit=limit,
    )


@app.command("get")
def get(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID")],
) -> None:
    """Get full details of a feedback item including votes.

    Examples:
      st feedback get a1b2c3d4-...
    """
    get_impl(item_id)


@app.command("vote")
def vote(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID to vote on")],
    session_id: Annotated[
        str | None, typer.Option("--session", help="Session ID casting the vote")
    ] = None,
    comment: Annotated[
        str | None, typer.Option("--comment", "-m", help="Optional comment")
    ] = None,
    agent_slug: Annotated[
        str | None, typer.Option("--agent", help="Agent slug")
    ] = None,
    model_used: Annotated[
        str | None, typer.Option("--model", help="Model used")
    ] = None,
) -> None:
    """Vote on an existing feedback item.

    Examples:
      st feedback vote a1b2c3d4 --session sess-123
      st feedback vote a1b2c3d4 --session sess-123 --comment "Hit this during autocode"
    """
    vote_impl(
        item_id,
        session_id=session_id,
        comment=comment,
        agent_slug=agent_slug,
        model_used=model_used,
    )


@app.command("resolve")
def resolve(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID to resolve")],
    note: Annotated[
        str | None, typer.Option("--note", "-n", help="Resolution note")
    ] = None,
) -> None:
    """Resolve a feedback item.

    Examples:
      st feedback resolve a1b2c3d4 --note "Fixed in commit abc123"
    """
    resolve_impl(item_id, note=note)


@app.command("summary")
def summary(
    project_id: Annotated[
        str | None, typer.Option("--project", "-p", help="Filter by project")
    ] = None,
    days: Annotated[int, typer.Option("--days", help="Lookback window in days")] = 30,
) -> None:
    """Get aggregated feedback summary.

    Examples:
      st feedback summary
      st feedback summary --project summitflow --days 7
    """
    summary_impl(project_id=project_id, days=days)
