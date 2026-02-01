"""Quality gate health commands for the CLI."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..output import output_error, output_json
from ..output_context import OutputContext

app = typer.Typer(help="Quality gate health and status")


@app.callback()
def health_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _format_health_compact(health: dict[str, Any]) -> None:
    """Format health summary in TOON style.

    Format:
    HEALTH:{project_id}:{PASS|FAIL}:unfixed={N}
    {check_type}:{PASS|FAIL}:err={N}|warn={N}|last={timestamp}
    """
    project_id = health.get("project_id", "unknown")
    overall = "PASS" if health.get("overall_pass") else "FAIL"
    unfixed = health.get("total_unfixed", 0)

    print(f"HEALTH:{project_id}:{overall}:unfixed={unfixed}")

    checks = health.get("checks", {})
    for check_type, details in checks.items():
        status = "PASS" if details.get("status") == "pass" else "FAIL"
        errors = details.get("error_count", 0)
        warnings = details.get("warning_count", 0)
        last_run = details.get("last_run", "never")
        if last_run != "never":
            # Truncate timestamp to just date/time
            last_run = last_run[:19] if len(last_run) > 19 else last_run
        print(f"  {check_type}:{status}:err={errors}|warn={warnings}|last={last_run}")


def _format_results_compact(results: dict[str, Any]) -> None:
    """Format check results in TOON style.

    Format:
    RESULTS[N]:unfixed={M}
    {id} {check_type:6} {status:4} {file}:{line} {message:50}
    """
    items = results.get("items", [])
    unfixed = results.get("unfixed_count", 0)

    print(f"RESULTS[{len(items)}]:unfixed={unfixed}")

    for item in items:
        result_id = item.get("id", "?")
        check_type = (item.get("check_type") or "")[:6].ljust(6)
        status = (item.get("status") or "")[:4].ljust(4)
        file_path = item.get("file_path") or "-"
        line = item.get("line_number") or "-"
        loc = f"{file_path}:{line}"
        if len(loc) > 40:
            loc = "..." + loc[-37:]
        loc = loc.ljust(40)
        message = item.get("error_message") or "-"
        if len(message) > 50:
            message = message[:47] + "..."
        print(f"  {result_id} {check_type} {status} {loc} {message}")


@app.callback(invoke_without_command=True)
def health_default(ctx: typer.Context) -> None:
    """Show quality gate health summary for current project.

    This is the default command when no subcommand is specified.

    Examples:
        st health
        st health --human
    """
    if ctx.invoked_subcommand is None:
        status(ctx)


@app.command()
def status(ctx: typer.Context) -> None:
    """Show quality gate health summary for current project.

    Displays the latest status for each check type (pytest, ruff, mypy, biome, tsc)
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
        _format_health_compact(result)
    else:
        output_json(result)


@app.command()
def results(
    ctx: typer.Context,
    check_type: Annotated[
        str | None,
        typer.Option("--type", "-t", help="Filter by check type (pytest, ruff, mypy, biome, tsc)"),
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

    Shows detailed check results with file locations and messages.
    Supports filtering by check type, status, and unfixed failures.

    Examples:
        st health results
        st health results --type pytest
        st health results --unfixed
        st health results -t ruff -s fail --limit 20
    """
    try:
        client = STClient()

        # Build query params
        params = [f"limit={limit}"]
        if check_type:
            params.append(f"check_type={check_type}")
        if status_filter:
            params.append(f"status={status_filter}")
        if unfixed:
            params.append("unfixed_only=true")

        query = "&".join(params)
        result = client.get(client._url(f"/quality/results?{query}"))
    except APIError as e:
        output_error(f"API error: {e.detail}")
        raise typer.Exit(1) from None
    except Exception as e:
        output_error(f"Failed to get results: {e}")
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        _format_results_compact(result)
    else:
        output_json(result)


@app.command()
def sync(
    ctx: typer.Context,
    check_type: Annotated[
        str,
        typer.Argument(help="Check type (pytest, ruff, mypy, biome, tsc)"),
    ],
    status_val: Annotated[
        str,
        typer.Argument(help="Status (pass, fail, error, skipped)"),
    ],
    error_count: Annotated[
        int,
        typer.Option("--errors", "-e", help="Number of errors"),
    ] = 0,
    warning_count: Annotated[
        int,
        typer.Option("--warnings", "-w", help="Number of warnings"),
    ] = 0,
    triggered_by: Annotated[
        str,
        typer.Option(
            "--triggered-by", "-b", help="What triggered the check (commit, manual, ci, agent)"
        ),
    ] = "commit",
) -> None:
    """Sync a quality check result from dt output.

    This command is typically called by dt (dev-tools.sh) after running checks.
    It records the check result in the quality_check_results table.

    Examples:
        st health sync pytest pass
        st health sync ruff fail --errors 5
        st health sync mypy fail --errors 3 --triggered-by manual
    """
    try:
        client = STClient()
        result = client._client.post(
            client._url("/quality/sync"),
            json={
                "check_type": check_type,
                "status": status_val,
                "error_count": error_count,
                "warning_count": warning_count,
                "triggered_by": triggered_by,
            },
        )

        if result.status_code >= 400:
            try:
                detail = result.json().get("detail", result.text)
            except Exception:
                detail = result.text
            output_error(f"API error: {detail}")
            raise typer.Exit(1) from None

        data = result.json()
    except APIError as e:
        output_error(f"API error: {e.detail}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Failed to sync: {e}")
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        synced = data.get("synced", False)
        created = data.get("created_count", 0)
        ct = data.get("check_type", check_type)
        st = data.get("status", status_val)
        status_word = "OK" if synced else "FAIL"
        print(f"SYNC:{status_word}:{ct}:{st}:created={created}")
    else:
        output_json(data)
