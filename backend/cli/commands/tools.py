"""Tools command - View operator catalog and Agent Hub usage metrics."""

from __future__ import annotations

import os
from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import output_error, output_json
from ..output_context import OutputContext
from ..tool_registry import list_operator_tools, tool_registry_path
from ._api_paths import ACCESS_CONTROL_METRICS_PATH
from ._http_errors import parse_error_detail, raise_connect_error, raise_timeout_error

app = typer.Typer(help="Operator tool catalog and Agent Hub usage metrics")


def _build_internal_headers() -> dict[str, str]:
    """Build env-backed internal headers for read-only Agent Hub admin surfaces."""
    secret = os.getenv("INTERNAL_SERVICE_SECRET", "").strip()
    if not secret:
        output_error(
            "INTERNAL_SERVICE_SECRET is not configured. "
            "st tools requires the shared internal Agent Hub auth header."
        )
        raise typer.Exit(1) from None
    return {"X-Agent-Hub-Internal": secret}


def _handle_response(response: httpx.Response, agent_hub_url: str) -> dict[str, Any]:
    """Validate and parse a successful HTTP response."""
    if response.status_code >= 400:
        detail = parse_error_detail(response)
        output_error(f"API error ({response.status_code}): {detail}")
        raise typer.Exit(1) from None
    return cast(dict[str, Any], response.json())


def _api_request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make request to Agent Hub admin API."""
    agent_hub_url = get_agent_hub_url()
    headers = _build_internal_headers()
    url = f"{agent_hub_url}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params, headers=headers)
            return _handle_response(response, agent_hub_url)
    except httpx.ConnectError as e:
        raise_connect_error("Agent Hub", agent_hub_url, e)
    except httpx.TimeoutException as e:
        raise_timeout_error("Agent Hub", agent_hub_url, 30.0, e)
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


def _format_catalog_compact(tools: list[dict[str, Any]]) -> None:
    """Format operator tools in compact TOON style."""
    print(f"TOOLS_CATALOG[{len(tools)}]:source={tool_registry_path()}")
    for tool in tools:
        canonical = tool.get("canonical", "?")
        replaces = ",".join(str(item) for item in tool.get("replaces", []) if item)
        safety = tool.get("safety", "?")
        summary = str(tool.get("summary", "")).strip()
        print(f"  {canonical}|safety:{safety}|replaces:{replaces}|{summary}")


@app.command()
def catalog(ctx: typer.Context) -> None:
    """Show canonical st operator tools from the shared registry."""
    tools = list_operator_tools()
    if ctx.obj.is_compact:
        _format_catalog_compact(tools)
    else:
        output_json({"source": str(tool_registry_path()), "tools": tools})


@app.command()
def status(
    ctx: typer.Context,
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
        ACCESS_CONTROL_METRICS_PATH,
        params={"hours": hours, "limit": limit},
    )

    if ctx.obj.is_compact:
        _format_status_compact(result)
    else:
        output_json(result)


@app.callback(invoke_without_command=True)
def tools_default(ctx: typer.Context) -> None:
    """Show operator catalog by default."""
    if ctx.obj is None:
        ctx.obj = OutputContext()
    if ctx.invoked_subcommand is None:
        catalog(ctx)
