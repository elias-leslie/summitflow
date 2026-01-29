"""Tools command - View tool/API usage metrics from Agent Hub."""

from __future__ import annotations

from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import is_compact, output_error, output_json

app = typer.Typer(help="Tool usage metrics (Agent Hub)")


def _api_request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make request to Agent Hub admin API."""
    agent_hub_url = get_agent_hub_url()
    headers = {"X-Agent-Hub-Internal": "agent-hub-internal-v1"}
    url = f"{agent_hub_url}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params, headers=headers)

            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                output_error(f"API error ({response.status_code}): {detail}")
                raise typer.Exit(1) from None

            return cast(dict[str, Any], response.json())
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None


def _format_status_compact(data: dict[str, Any]) -> None:
    """Format tool status in TOON style."""
    summary = data.get("summary", {})
    by_endpoint = data.get("by_endpoint", [])
    by_tool_type = data.get("by_tool_type", [])

    total = summary.get("total_requests", 0)
    success_rate = summary.get("success_rate", 100.0)
    avg_latency = summary.get("avg_latency_ms", 0)

    print(f"TOOLS[24h]:requests={total} success={success_rate:.1f}% latency={avg_latency:.0f}ms")

    if by_tool_type:
        parts = [f"{t['tool_type']}={t['count']}" for t in by_tool_type]
        print(f"  By type: {' '.join(parts)}")

    if by_endpoint:
        print("  Top endpoints:")
        for ep in by_endpoint[:5]:
            endpoint = ep.get("endpoint", "?")[:40]
            count = ep.get("count", 0)
            rate = ep.get("success_rate", 100.0)
            latency = ep.get("avg_latency_ms", 0)
            print(f"    {endpoint}  {count} reqs  {rate:.1f}%  {latency:.0f}ms")


@app.command()
def status(
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max endpoints to show")] = 10,
) -> None:
    """Show tool/API usage metrics.

    Displays aggregated metrics from request_logs:
    - Total requests, success rate, average latency
    - Breakdown by tool type (api/cli/sdk)
    - Top endpoints by request count

    Examples:
        st tools status
        st tools status --hours 1
        st tools status --limit 20
    """
    result = _api_request(
        "/api/access-control/metrics",
        params={"hours": hours, "limit": limit},
    )

    if is_compact():
        _format_status_compact(result)
    else:
        output_json(result)


@app.callback(invoke_without_command=True)
def tools_default(ctx: typer.Context) -> None:
    """Show tool status (default command)."""
    if ctx.invoked_subcommand is None:
        status()
