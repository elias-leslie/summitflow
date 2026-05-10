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
ips_app = typer.Typer(help="Investment Policy Statement targets (allocation goals)")
app.add_typer(tlh_app, name="tlh")
app.add_typer(ips_app, name="ips")


# Map of `st portfolio schema <command>` aliases to the OpenAPI path the
# response schema lives under. Adding a new endpoint means adding one
# entry here — the CLI will read /openapi.json and project the response
# schema for that path.
_SCHEMA_PATHS: dict[str, tuple[str, str]] = {
    "tlh-candidates": ("/api/portfolio/tlh/candidates", "get"),
    "tlh-wash-sale-check": ("/api/portfolio/tlh/wash-sale-check", "post"),
    "drift": ("/api/portfolio/ips/drift", "get"),
    "rebalance": ("/api/portfolio/ips/rebalance", "post"),
    "ips-targets": ("/api/portfolio/ips/targets", "get"),
    "catalysts-upcoming": ("/api/catalysts/upcoming", "get"),
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


# ----------------------------------------------------------------------
# IPS / drift / rebalance — F3 surface
# ----------------------------------------------------------------------


_FRIENDLY_CLASS = {
    "us_equity": "US stocks",
    "intl_equity": "Foreign stocks",
    "bonds": "Bonds",
    "cash": "Cash",
    "alts": "Alternatives",
    "real_estate": "Real estate",
    "unclassified": "Unclassified",
}


def _human_drift_summary(summary: dict[str, Any]) -> str:
    oob = int(summary.get("classes_out_of_band", 0) or 0)
    max_drift = float(summary.get("max_drift_pct", 0) or 0) * 100
    total = float(summary.get("total_value", 0) or 0)
    if oob == 0:
        return (
            f"On plan. Total ${total:,.0f}. "
            f"Worst category is {max_drift:.1f}% off goal — inside wiggle room."
        )
    return (
        f"{oob} category{'s' if oob != 1 else ''} outside wiggle room. "
        f"Worst is {max_drift:.1f}% off goal. Total ${total:,.0f}."
    )


def _human_drift_report(report: dict[str, Any]) -> str:
    rows = report.get("rows", []) or []
    total = float(report.get("total_value", 0) or 0)
    lines = [f"Allocation snapshot for {report.get('snapshot_date')} — total ${total:,.0f}:", ""]
    for row in rows:
        klass = _FRIENDLY_CLASS.get(row.get("asset_class"), row.get("asset_class"))
        actual = float(row.get("actual_pct", 0) or 0) * 100
        target = float(row.get("target_pct", 0) or 0) * 100
        drift = float(row.get("drift_pct", 0) or 0) * 100
        flag = "  outside wiggle room" if row.get("out_of_band") else ""
        lines.append(
            f"  - {klass}: {actual:.1f}% (goal {target:.1f}%, off {drift:+.1f}%){flag}"
        )
    missing = report.get("classes_missing_targets") or []
    if missing:
        lines.append("")
        lines.append("Held but no goal set: " + ", ".join(_FRIENDLY_CLASS.get(c, c) for c in missing))
    return "\n".join(lines)


def _human_rebalance_plan(plan: dict[str, Any]) -> str:
    trades = plan.get("trades", []) or []
    if not trades:
        return "Already on plan — no trades suggested."
    lines = [
        f"{len(trades)} trade(s) to get back on plan "
        f"(total buys ${float(plan.get('total_buy_value', 0) or 0):,.0f}, "
        f"total sells ${float(plan.get('total_sell_value', 0) or 0):,.0f}):",
        "",
    ]
    for trade in trades:
        action = "BUY " if trade.get("action") == "buy" else "SELL"
        symbol = trade.get("symbol", "?")
        klass = _FRIENDLY_CLASS.get(trade.get("asset_class"), trade.get("asset_class"))
        amount = float(trade.get("estimated_value", 0) or 0)
        account = trade.get("account_type", trade.get("account_id"))
        suffix = ""
        if trade.get("wash_sale_conflict"):
            reason = trade.get("wash_sale_reason") or "recent buy blocks this sale"
            suffix = f" — BLOCKED: {reason}"
        lines.append(f"  {action} ${amount:,.0f} of {symbol} ({klass}) in {account}{suffix}")
    if plan.get("wash_sale_conflicts"):
        lines.append("")
        lines.append(
            f"Note: {plan['wash_sale_conflicts']} sell(s) blocked by recent buys — "
            "switch the conflicting account or wait 31 days."
        )
    return "\n".join(lines)


@app.command("drift")
def drift(
    scope: Annotated[str, typer.Option("--scope", help="household | account")] = "household",
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = "default",
    summary: Annotated[bool, typer.Option("--summary/--no-summary", help="Compact digest (default) vs full row table")] = True,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Show how far each asset class is from its goal allocation.

    Default response is a single-line digest. Pass ``--no-summary`` for
    the full per-class table.
    """
    if scope not in ("household", "account"):
        output_error(f"--scope must be 'household' or 'account', got {scope!r}")
        raise typer.Exit(3)
    params: dict[str, Any] = {"scope": scope, "scope_id": scope_id, "summary": str(summary).lower()}
    try:
        with _client(remote)[0] as client:
            data = client.get("/api/portfolio/ips/drift", params=params)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)

    if not isinstance(data, dict):
        data = {}
    envelope = {
        "ok": True,
        "schema_version": 1,
        "data": data,
        "meta": {"scope": scope, "scope_id": scope_id, "summary": summary},
    }
    summary_text = _human_drift_summary(data) if summary else _human_drift_report(data)
    _emit(envelope, human=human, summary_text=summary_text)


@app.command("rebalance")
def rebalance(
    scope: Annotated[str, typer.Option("--scope", help="household | account")] = "household",
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = "default",
    prefer_tax_advantaged: Annotated[bool, typer.Option("--prefer-tax-advantaged/--no-prefer-tax-advantaged", help="Route buys to Roth/IRA/401k first")] = True,
    prefer_ltcg: Annotated[bool, typer.Option("--prefer-ltcg/--no-prefer-ltcg", help="Prefer long-term over short-term gains on sells")] = True,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Propose tax-aware trades to close the drift gap.

    Three-pass: route buys to tax-advantaged first, prefer
    long-term losses/gains over short-term on sells, run wash-sale
    check on every taxable sell and reroute or flag conflicts.
    """
    if scope not in ("household", "account"):
        output_error(f"--scope must be 'household' or 'account', got {scope!r}")
        raise typer.Exit(3)
    body = {
        "scope": scope,
        "scope_id": scope_id,
        "prefer_tax_advantaged": prefer_tax_advantaged,
        "prefer_ltcg": prefer_ltcg,
    }
    try:
        with _client(remote)[0] as client:
            plan = client.post("/api/portfolio/ips/rebalance", json_body=body)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)

    if not isinstance(plan, dict):
        plan = {}
    envelope = {
        "ok": True,
        "schema_version": 1,
        "data": plan,
        "meta": {"scope": scope, "scope_id": scope_id},
    }
    _emit(envelope, human=human, summary_text=_human_rebalance_plan(plan))


@ips_app.command("list")
def ips_list(
    scope: Annotated[str, typer.Option("--scope", help="household | account")] = "household",
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = "default",
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """List allocation goals for one scope."""
    if scope not in ("household", "account"):
        output_error(f"--scope must be 'household' or 'account', got {scope!r}")
        raise typer.Exit(3)
    params: dict[str, Any] = {"scope": scope, "scope_id": scope_id}
    try:
        with _client(remote)[0] as client:
            rows = client.get("/api/portfolio/ips/targets", params=params)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)
    if not isinstance(rows, list):
        rows = []
    envelope = {
        "ok": True,
        "schema_version": 1,
        "data": rows,
        "meta": {"count": len(rows), "scope": scope, "scope_id": scope_id},
    }
    if human:
        if not rows:
            text = "No allocation goals set yet."
        else:
            lines = ["Allocation goals:"]
            for row in rows:
                klass = _FRIENDLY_CLASS.get(row.get("asset_class"), row.get("asset_class"))
                target = float(row.get("target_pct", 0) or 0) * 100
                band = float(row.get("drift_band_pct", 0) or 0) * 100
                lines.append(f"  - {klass}: {target:.1f}% (wiggle room ±{band:.1f}%)")
            text = "\n".join(lines)
        _emit(envelope, human=True, summary_text=text)
    else:
        _emit(envelope, human=False)


@ips_app.command("set")
def ips_set(
    asset_class: Annotated[str, typer.Option("--asset-class", help="us_equity | intl_equity | bonds | cash | alts | real_estate")],
    target: Annotated[float, typer.Option("--target", min=0.0, max=1.0, help="Target weight (0-1)")],
    band: Annotated[float, typer.Option("--band", min=0.0, max=1.0, help="Wiggle room ± (0-1)")] = 0.05,
    notes: Annotated[str | None, typer.Option("--notes", help="Optional rationale")] = None,
    scope: Annotated[str, typer.Option("--scope", help="household | account")] = "household",
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = "default",
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Set or update one allocation goal (upsert)."""
    if scope not in ("household", "account"):
        output_error(f"--scope must be 'household' or 'account', got {scope!r}")
        raise typer.Exit(3)
    body = {
        "scope": scope,
        "scope_id": scope_id,
        "asset_class": asset_class,
        "target_pct": target,
        "drift_band_pct": band,
        "notes": notes,
    }
    try:
        with _client(remote)[0] as client:
            row = client.put("/api/portfolio/ips/targets", json_body=body)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)

    if not isinstance(row, dict):
        row = {}
    envelope = {"ok": True, "schema_version": 1, "data": row, "meta": {"upsert": True}}
    if human:
        klass = _FRIENDLY_CLASS.get(asset_class, asset_class)
        text = f"Set {klass} goal to {target * 100:.1f}% (wiggle room ±{band * 100:.1f}%)."
        _emit(envelope, human=True, summary_text=text)
    else:
        _emit(envelope, human=False)


# ----------------------------------------------------------------------
# Catalysts — F4 surface
# ----------------------------------------------------------------------


_FRIENDLY_KIND = {
    "earnings": "Earnings",
    "ex_dividend": "Last day for dividend",
    "fomc": "Fed interest-rate meeting",
}


def _human_catalysts(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No upcoming events in the requested window."
    lines = [f"{len(rows)} upcoming event(s):", ""]
    for row in rows:
        raw_kind = row.get("kind") or ""
        kind = _FRIENDLY_KIND.get(raw_kind, raw_kind)
        symbol = row.get("symbol") or ""
        target = symbol or "(macro)"
        date_str = row.get("date", "?")
        days_until = row.get("days_until")
        when = f"in {days_until} day{'s' if days_until != 1 else ''}" if days_until is not None else date_str
        lines.append(f"  - {target}: {kind} on {date_str} ({when})")
    return "\n".join(lines)


@app.command("catalysts")
def catalysts(
    days: Annotated[int, typer.Option("--days", min=1, max=365, help="Lookahead window in days")] = 14,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200, help="Maximum events to return")] = 20,
    kinds: Annotated[
        str | None,
        typer.Option("--kinds", help="Comma-separated subset of earnings,ex_dividend,fomc"),
    ] = None,
    include_watchlist: Annotated[
        bool,
        typer.Option(
            "--include-watchlist/--no-include-watchlist",
            help="Include watchlist symbols (in addition to portfolio holdings)",
        ),
    ] = True,
    symbols: Annotated[
        str | None,
        typer.Option("--symbols", help="Comma-separated symbols (overrides default universe)"),
    ] = None,
    detail: Annotated[
        bool,
        typer.Option("--detail", help="Add time_of_day, confirmed, source to each row"),
    ] = False,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """List upcoming catalysts (earnings, ex-dividend, FOMC) sorted by date.

    Compact JSON projection by default — ``{symbol, kind, date,
    days_until}`` per row. Pass ``--detail`` for ``time_of_day``,
    ``confirmed``, and ``source`` fields. ``--kinds`` narrows the merge
    to a subset.
    """
    params: dict[str, Any] = {
        "days": days,
        "limit": limit,
        "include_watchlist": str(include_watchlist).lower(),
        "detail": str(detail).lower(),
    }
    if kinds:
        params["kinds"] = kinds
    if symbols:
        params["symbols"] = symbols
    try:
        with _client(remote)[0] as client:
            data = client.get("/api/catalysts/upcoming", params=params)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)

    if not isinstance(data, dict):
        data = {}
    rows = data.get("catalysts") or []
    envelope = {
        "ok": True,
        "schema_version": 1,
        "data": data,
        "meta": {"count": len(rows), "limit": limit, "days": days},
    }
    _emit(envelope, human=human, summary_text=_human_catalysts(rows))
