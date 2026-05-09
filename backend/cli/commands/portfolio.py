"""``st portfolio`` — agent-facing CLI surface for portfolio-ai.

Each subcommand is a thin client over portfolio-ai's HTTP routers; no
analytics live here. The router serializes a Pydantic contract; the CLI
passes the dict through unchanged in JSON mode and translates a small
set of fields for ``--human``.

Exit codes (per plan F6):

* ``0`` success
* ``1`` HTTP / business error (the server returned a response)
* ``2`` connection failure (the portfolio-ai backend is unreachable)
* ``3`` invalid input flags (Typer's standard usage errors)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from typing import Annotated, Any

import typer

from .._client_base import APIError
from .._portfolio_client import (
    PortfolioClient,
    PortfolioConnectError,
    ResolvedURL,
    resolve_portfolio_api_url,
)
from ..output import output_error, output_json

app = typer.Typer(help="Agent-facing portfolio analytics (TLH, IPS, drift, catalysts, retirement)")
tlh_app = typer.Typer(help="Tax-loss harvesting + wash-sale detection")
app.add_typer(tlh_app, name="tlh")


# Map of `st portfolio schema <command>` aliases to the OpenAPI path the
# response schema lives under. Adding a new endpoint means adding one
# entry here — the CLI will read /openapi.json and project the response
# schema for that path.
_SCHEMA_PATHS: dict[str, tuple[str, str]] = {
    "tlh-candidates": ("/api/portfolio/tlh/candidates", "get"),
    "tlh-wash-sale-check": ("/api/portfolio/tlh/wash-sale-check", "post"),
}


def _client(remote: bool) -> tuple[PortfolioClient, ResolvedURL]:
    resolved = resolve_portfolio_api_url(remote=remote)
    return PortfolioClient(resolved.url), resolved


def _handle_connect(exc: PortfolioConnectError) -> None:
    """Emit the unreachable envelope and exit ``2``."""
    payload = {
        "ok": False,
        "error": "portfolio_api_unreachable",
        "url": exc.url,
        "detail": exc.detail,
        "hint": "Set ST_PORTFOLIO_API_URL or start the portfolio-ai backend",
    }
    print(json.dumps(payload), file=sys.stderr)
    raise typer.Exit(2)


def _handle_api_error(exc: APIError) -> None:
    """Emit the HTTP-error envelope and exit ``1``."""
    detail = exc.detail
    if isinstance(detail, dict):
        error_code = detail.get("error") or "http_error"
        message = detail.get("detail") or detail.get("message") or json.dumps(detail)
    else:
        error_code = "http_error"
        message = str(detail)
    payload = {"ok": False, "status": exc.status_code, "error": error_code, "detail": message}
    print(json.dumps(payload), file=sys.stderr)
    raise typer.Exit(1)


def _emit(data: Any, *, human: bool, summary_text: str | None = None) -> None:
    """Emit ``data`` as JSON; with ``--human`` use ``summary_text`` if provided."""
    if human and summary_text is not None:
        typer.echo(summary_text)
        return
    output_json(data)


def _human_candidates(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No tax-saving sales found."
    lines = [
        f"Found {len(rows)} sale(s) that could lower this year's taxes:",
        "",
    ]
    for row in rows:
        symbol = row.get("symbol", "?")
        loss = float(row.get("unrealized_loss", 0) or 0)
        loss_pct = float(row.get("unrealized_loss_pct", 0) or 0) * 100
        account = row.get("account_id", "?")
        prefix = "  - "
        lines.append(
            f"{prefix}{symbol}: paper loss ${loss:,.2f} ({loss_pct:+.2f}%) "
            f"in account {account}"
        )
        if row.get("wash_sale_blocked"):
            reason = row.get("wash_sale_reason") or "recent buys block this sale"
            lines.append(f"      blocked: {reason}")
        replacement = row.get("replacement")
        if isinstance(replacement, dict):
            to_symbol = replacement.get("to_symbol")
            confidence = replacement.get("confidence")
            if to_symbol:
                lines.append(f"      possible replacement: {to_symbol} ({confidence})")
    return "\n".join(lines)


def _human_wash_sale(verdict: dict[str, Any]) -> str:
    symbol = verdict.get("symbol", "?")
    sell_date = verdict.get("sell_date", "?")
    if verdict.get("blocked"):
        reason = verdict.get("reason") or "recent buys block this sale"
        lines = [
            f"Selling {symbol} on {sell_date} would void the tax benefit.",
            f"Reason: {reason}",
        ]
        for buy in verdict.get("conflicting_buys", []):
            offset = buy.get("days_offset")
            shares = buy.get("shares")
            account = buy.get("account_id")
            trade_date = buy.get("trade_date")
            lines.append(
                f"  - {shares} share(s) bought on {trade_date} "
                f"({offset:+d} days) in account {account}"
            )
        return "\n".join(lines)
    return f"Selling {symbol} on {sell_date} is clear: no conflicting buys in the 61-day window."


@tlh_app.command("candidates")
def tlh_candidates(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100, help="Maximum candidates to return")] = 20,
    min_loss: Annotated[float, typer.Option("--min-loss", min=0.0, help="Minimum dollar loss")] = 500.0,
    min_loss_pct: Annotated[float, typer.Option("--min-loss-pct", min=0.0, max=1.0, help="Minimum loss as fraction of cost basis")] = 0.05,
    detail: Annotated[bool, typer.Option("--detail", help="Include replacement, holding period, ST/LT split, wash-sale annotations")] = False,
    summary: Annotated[bool, typer.Option("--summary", help="Single-line digest only")] = False,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use the production hosts.production_api endpoint")] = False,
) -> None:
    """List taxable positions trading below cost (most-actionable first).

    Compact JSON by default. ``--detail`` adds replacement, holding
    period, ST/LT loss split, and wash-sale annotations.
    """
    params: dict[str, Any] = {
        "limit": limit,
        "min_loss": min_loss,
        "min_loss_pct": min_loss_pct,
        "detail": str(detail).lower(),
    }
    try:
        with _client(remote)[0] as client:
            rows = client.get("/api/portfolio/tlh/candidates", params=params)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)

    if not isinstance(rows, list):
        rows = []

    if summary:
        digest = {
            "ok": True,
            "schema_version": 1,
            "data": {
                "count": len(rows),
                "total_loss": round(sum(float(r.get("unrealized_loss", 0) or 0) for r in rows), 2),
                "blocked_count": sum(1 for r in rows if r.get("wash_sale_blocked")),
            },
            "meta": {"limit": limit},
        }
        _emit(digest, human=human, summary_text=(
            f"{digest['data']['count']} candidate(s); "
            f"total paper loss ${digest['data']['total_loss']:,.2f}; "
            f"{digest['data']['blocked_count']} blocked by recent buys"
        ))
        return

    envelope = {
        "ok": True,
        "schema_version": 1,
        "data": rows,
        "meta": {"count": len(rows), "limit": limit, "next_cursor": None},
    }
    _emit(envelope, human=human, summary_text=_human_candidates(rows))


@tlh_app.command("wash-sale-check")
def tlh_wash_sale_check(
    symbol: Annotated[str, typer.Option("--symbol", help="Ticker to check (e.g. AAPL)")],
    sell_date: Annotated[str, typer.Option("--sell-date", help="Proposed sell date (YYYY-MM-DD)")],
    household_id: Annotated[str, typer.Option("--household-id", help="Household scope for cross-account check")],
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Check the household's 61-day window for substantially-identical buys.

    Per IRS Pub 550 and Rev. Rul. 2008-5, the scan covers spouse
    accounts and tax-advantaged accounts (Roth, IRA, 401k, HSA).
    """
    try:
        date.fromisoformat(sell_date)
    except ValueError as exc:
        output_error(f"Invalid --sell-date {sell_date!r}: {exc}")
        raise typer.Exit(3) from None

    body = {"symbol": symbol, "sell_date": sell_date, "household_id": household_id}
    try:
        with _client(remote)[0] as client:
            verdict = client.post("/api/portfolio/tlh/wash-sale-check", json_body=body)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)

    if not isinstance(verdict, dict):
        verdict = {}

    envelope = {
        "ok": True,
        "schema_version": 1,
        "data": verdict,
        "meta": {"symbol": symbol, "sell_date": sell_date},
    }
    _emit(envelope, human=human, summary_text=_human_wash_sale(verdict))


@app.command("schema")
def schema(
    command: Annotated[str, typer.Argument(help="Subcommand to introspect (e.g. tlh-candidates)")],
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Print the response JSON schema for a portfolio subcommand.

    Reads ``/openapi.json`` from the portfolio-ai backend and projects
    the response schema for the path that backs ``<command>``. This
    lets agents introspect contracts without a trial call.
    """
    if command not in _SCHEMA_PATHS:
        output_error(
            f"Unknown schema target {command!r}. Choices: {', '.join(sorted(_SCHEMA_PATHS))}"
        )
        raise typer.Exit(3)

    path, method = _SCHEMA_PATHS[command]
    try:
        with _client(remote)[0] as client:
            spec = client.get("/openapi.json")
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)

    if not isinstance(spec, dict):
        output_error("portfolio-ai /openapi.json did not return a JSON object")
        raise typer.Exit(1)

    paths = spec.get("paths", {})
    operation = paths.get(path, {}).get(method)
    if not isinstance(operation, dict):
        output_error(f"openapi spec has no {method.upper()} {path}")
        raise typer.Exit(1)

    response = (
        operation.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
    )
    schema_obj = response.get("schema") or {}
    components = spec.get("components", {}).get("schemas", {})
    output_json({"command": command, "path": path, "method": method.upper(), "schema": schema_obj, "components": components})
