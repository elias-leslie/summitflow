"""Quality gate health commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import output_error, output_json
from ..output_context import OutputContext
from ._health_helpers import (
    build_results_query,
    build_sync_payload,
    format_health_compact,
    format_results_compact,
    print_sync_compact,
)
from ._http_errors import parse_error_detail

app = typer.Typer(help="Quality gate health and status")


@app.callback(invoke_without_command=True)
def health_default(ctx: typer.Context) -> None:
    """Show quality gate health summary (default when no subcommand given)."""
    if ctx.obj is None:
        ctx.obj = OutputContext()
    if ctx.invoked_subcommand is None:
        status(ctx)


@app.command()
def status(ctx: typer.Context) -> None:
    """Show quality gate health summary for current project.

    Displays the latest status for each check type (pytest, vitest, ruff, types, biome, tsc)
    and the overall pass/fail status.

    Examples:
        st health status
        st health status --human
    """
    try:
        client = STClient()
        result = client.get(client._url("/quality/health"))
    except APIError as e:
        output_error(f"API error: {e.detail}")
        raise typer.Exit(1) from None
    except Exception as e:
        output_error(f"Failed to get health: {e}")
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        format_health_compact(result)
    else:
        output_json(result)


@app.command()
def results(
    ctx: typer.Context,
    check_type: Annotated[
        str | None,
        typer.Option("--type", "-t", help="Filter by check type (pytest, vitest, ruff, types, biome, tsc)"),
    ] = None,
    status_filter: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (pass, fail, error, skipped)"),
    ] = None,
    unfixed: Annotated[
        bool,
        typer.Option("--unfixed", "-u", help="Show only unfixed failures"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum number of results"),
    ] = 50,
) -> None:
    """List quality check results for current project.

    Supports filtering by check type, status, and unfixed failures.

    Examples: st health results | st health results --type pytest
              st health results --unfixed | st health results -t ruff -s fail --limit 20
    """
    try:
        client = STClient()
        query = build_results_query(limit, check_type, status_filter, unfixed)
        result = client.get(client._url(f"/quality/results?{query}"))
    except APIError as e:
        output_error(f"API error: {e.detail}")
        raise typer.Exit(1) from None
    except Exception as e:
        output_error(f"Failed to get results: {e}")
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        format_results_compact(result)
    else:
        output_json(result)


@app.command()
def sync(
    ctx: typer.Context,
    check_type: Annotated[str, typer.Argument(help="Check type (pytest, vitest, ruff, types, biome, tsc)")],
    status_val: Annotated[str, typer.Argument(help="Status (pass, fail, error, skipped)")],
    error_count: Annotated[int, typer.Option("--errors", "-e", help="Number of errors")] = 0,
    warning_count: Annotated[int, typer.Option("--warnings", "-w", help="Number of warnings")] = 0,
    triggered_by: Annotated[
        str,
        typer.Option("--triggered-by", "-b", help="What triggered the check (commit, manual, ci, agent)"),
    ] = "commit",
) -> None:
    """Sync a quality check result from st check output.

    Typically called by st check after running checks. Records
    results in the quality_check_results table.

    Examples:
        st health sync pytest pass
        st health sync vitest fail --errors 2
        st health sync ruff fail --errors 5
        st health sync types fail --errors 3 --triggered-by manual
    """
    try:
        client = STClient()
        payload = build_sync_payload(check_type, status_val, error_count, warning_count, triggered_by)
        response = client._client.post(client._url("/quality/sync"), json=payload)

        if response.status_code >= 400:
            output_error(f"API error: {parse_error_detail(response)}")
            raise typer.Exit(1) from None

        data = response.json()
    except APIError as e:
        output_error(f"API error: {e.detail}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Failed to sync: {e}")
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print_sync_compact(data, check_type, status_val)
    else:
        output_json(data)
