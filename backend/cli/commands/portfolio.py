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
from ..lib.usage import usage
from ..output import output_error, output_json

SCHEMA_VERSION = 1
HTTP_OK = "200"
JSON_CONTENT_TYPE = "application/json"
DEFAULT_SCOPE = "default"
VALID_SCOPES = ("household", "account")
INVALID_SCOPE_MSG = "--scope must be 'household' or 'account', got {!r}"

# API endpoints
EP_TLH_CANDIDATES = "/api/portfolio/tlh/candidates"
EP_TLH_WASHSALE = "/api/portfolio/tlh/wash-sale-check"
EP_IPS_DRIFT = "/api/portfolio/ips/drift"
EP_IPS_REBALANCE = "/api/portfolio/ips/rebalance"
EP_IPS_TARGETS = "/api/portfolio/ips/targets"
EP_CATALYSTS = "/api/catalysts/upcoming"
EP_PORTFOLIO = "/api/portfolio"
EP_PORTFOLIO_ANALYTICS = "/api/portfolio/analytics"
EP_PORTFOLIO_JENNY = "/api/portfolio/jenny"
EP_MARKET_STATUS = "/api/market/status"
EP_RETIREMENT_SCENARIOS = "/api/retirement/scenarios"
EP_HOUSEHOLD_DASHBOARD = "/api/household/dashboard"
EP_HOUSEHOLD_SPENDING = "/api/household/spending"
EP_SYMBOL_INTELLIGENCE = "/api/symbols/{symbol}/intelligence"
EP_MACRO_CONDITIONS = "/api/macro/conditions"
EP_OPENAPI = "/openapi.json"

# Human-readable labels
FRIENDLY_CLASS = {
    "us_equity": "US stocks",
    "intl_equity": "Foreign stocks",
    "bonds": "Bonds",
    "cash": "Cash",
    "alts": "Alternatives",
    "real_estate": "Real estate",
    "unclassified": "Unclassified",
}
FRIENDLY_KIND = {
    "earnings": "Earnings",
    "ex_dividend": "Last day for dividend",
    "fomc": "Fed interest-rate meeting",
}

FRIENDLY_CLASS = {
    "us_equity": "US stocks",
    "intl_equity": "Foreign stocks",
    "bonds": "Bonds",
    "cash": "Cash",
    "alts": "Alternatives",
    "real_estate": "Real estate",
    "unclassified": "Unclassified",
}
FRIENDLY_KIND = {
    "earnings": "Earnings",
    "ex_dividend": "Last day for dividend",
    "fomc": "Fed interest-rate meeting",
}

# Map of schema-alias → (path, method)
_SCHEMA_PATHS: dict[str, tuple[str, str]] = {
    "tlh-candidates": (EP_TLH_CANDIDATES, "get"),
    "tlh-wash-sale-check": (EP_TLH_WASHSALE, "post"),
    "drift": (EP_IPS_DRIFT, "get"),
    "rebalance": (EP_IPS_REBALANCE, "post"),
    "ips-targets": (EP_IPS_TARGETS, "get"),
    "catalysts-upcoming": (EP_CATALYSTS, "get"),
    "positions": (EP_PORTFOLIO, "get"),
    "briefing-context": (EP_PORTFOLIO, "get"),
    "market-status": (EP_MARKET_STATUS, "get"),
    "retirement-run": (EP_RETIREMENT_SCENARIOS, "post"),
    "retirement-list": (EP_RETIREMENT_SCENARIOS, "get"),
    "retirement-show": (f"{EP_RETIREMENT_SCENARIOS}/{{scenario_id}}", "get"),
}


# App hierarchy
app = typer.Typer(help="Agent-facing portfolio analytics (TLH, IPS, drift, catalysts, retirement)")
tlh_app = typer.Typer(help="Tax-loss harvesting + wash-sale detection")
ips_app = typer.Typer(help="Investment Policy Statement targets (allocation goals)")
retirement_app = typer.Typer(help="Stress-test your retirement plan against thousands of futures")
app.add_typer(tlh_app, name="tlh")
app.add_typer(ips_app, name="ips")
app.add_typer(retirement_app, name="retirement-plan")


# ─── helpers ────────────────────────────────────────────────────────────────────

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


def _get(remote: bool, path: str, *, params: dict[str, Any] | None = None) -> Any:
    try:
        with _client(remote)[0] as client:
            return client.get(path, params=params)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)


def _post_or_put(remote: bool, path: str, *, json_body: dict[str, Any], method: str = "post") -> Any:
    """POST or PUT to the API; _post is used more often, so default to post."""
    try:
        with _client(remote)[0] as client:
            if method == "put":
                return client.put(path, json_body=json_body)
            return client.post(path, json_body=json_body)
    except PortfolioConnectError as exc:
        _handle_connect(exc)
    except APIError as exc:
        _handle_api_error(exc)


def _safe_cast(value: Any, *, kind: str) -> Any:
    """Cast to dict/list or return empty. kind is 'dict' or 'list'."""
    if kind == "list":
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []
    return value if isinstance(value, dict) else {}


def _as_dict(value: Any) -> dict[str, Any]:
    return _safe_cast(value, kind="dict")


def _as_list(value: Any) -> list[dict[str, Any]]:
    return _safe_cast(value, kind="list")


def _success_envelope(data: Any, meta: dict[str, Any]) -> dict[str, Any]:
    """Alias for callers not yet migrated to _envelope."""
    return _envelope(data, meta)


def _envelope(data: Any, meta: dict[str, Any], *, digest: bool = False) -> dict[str, Any]:
    """Build success envelope. digest=True computes TLH summary fields inline."""
    if digest:
        rows = data if isinstance(data, list) else []
        data = {
            "count": len(rows),
            "total_loss": round(sum(float(r.get("unrealized_loss", 0) or 0) for r in rows), 2),
            "blocked_count": sum(1 for r in rows if r.get("wash_sale_blocked")),
        }
    return {"ok": True, "schema_version": SCHEMA_VERSION, "data": data, "meta": meta}


def _bool_param(value: bool) -> str:
    return str(value).lower()


def _require_scope(scope: str) -> None:
    if scope not in VALID_SCOPES:
        output_error(INVALID_SCOPE_MSG.format(scope))
        raise typer.Exit(3)


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _position_value(position: dict[str, Any]) -> float:
    value = _num(position.get("current_value"))
    if value is not None:
        return value
    price = _num(position.get("current_price"))
    shares = _num(position.get("shares"))
    if price is not None and shares is not None:
        return price * shares
    return 0.0


def _position_digest(position: dict[str, Any], total_value: float) -> dict[str, Any]:
    current_value = _position_value(position)
    weight = current_value / total_value if total_value > 0 else None
    return {
        "symbol": position.get("symbol"),
        "account_id": position.get("account_id"),
        "position_type": position.get("position_type"),
        "shares": position.get("shares"),
        "current_price": position.get("current_price"),
        "current_value": current_value,
        "weight_pct": round(weight * 100, 2) if weight is not None else None,
        "gain_pct": position.get("gain_pct"),
        "gain": position.get("gain"),
        "price_updated_at": position.get("price_updated_at"),
        "price_source": position.get("price_source"),
    }


def _portfolio_position_payload(portfolio: dict[str, Any], *, limit: int) -> dict[str, Any]:
    positions = _as_list(portfolio.get("positions"))
    total_value = _num(portfolio.get("effective_total_value")) or _num(portfolio.get("total_value")) or 0.0
    rows = [_position_digest(position, total_value) for position in positions]
    rows.sort(key=lambda row: abs(_num(row.get("current_value")) or 0.0), reverse=True)
    return {
        "as_of": portfolio.get("quotes_updated_at"),
        "quote_freshness_status": portfolio.get("quote_freshness_status"),
        "quote_freshness_label": portfolio.get("quote_freshness_label"),
        "total_value": total_value,
        "total_gain": portfolio.get("total_gain"),
        "total_gain_pct": portfolio.get("total_gain_pct"),
        "cash_balance_total": portfolio.get("cash_balance_total"),
        "num_positions": len(positions),
        "positions": rows[:limit],
    }


def _jenny_position_views(jenny: dict[str, Any], symbols: set[str]) -> list[dict[str, Any]]:
    rows = []
    for review in _as_list(jenny.get("symbol_reviews")):
        symbol = str(review.get("symbol") or "").upper()
        if symbols and symbol not in symbols:
            continue
        rows.append({
            "symbol": symbol,
            "final_verdict": review.get("final_verdict"),
            "average_confidence": review.get("average_confidence"),
            "thesis_status": review.get("thesis_status"),
            "thesis_action": review.get("thesis_action"),
            "management_action": review.get("management_action"),
            "position_gain_pct": review.get("position_gain_pct"),
            "position_weight_pct": review.get("position_weight_pct"),
            "reasons": (review.get("reasons") or [])[:4],
        })
    return rows


def _impact_watchlist(
    positions: list[dict[str, Any]],
    jenny_views: list[dict[str, Any]],
    catalysts: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in positions:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        current = by_symbol.setdefault(symbol, {"symbol": symbol, "accounts": [], "current_value": 0.0})
        current["accounts"].append(row)
        current["current_value"] = float(current.get("current_value") or 0.0) + float(_num(row.get("current_value")) or 0.0)
        if current.get("weight_pct") is None and row.get("weight_pct") is not None:
            current["weight_pct"] = 0.0
        if row.get("weight_pct") is not None:
            current["weight_pct"] = round(float(current.get("weight_pct") or 0.0) + float(row.get("weight_pct") or 0.0), 2)
    for view in jenny_views:
        symbol = str(view.get("symbol") or "").upper()
        by_symbol.setdefault(symbol, {"symbol": symbol}).update({"jenny_review": view})
    for catalyst in catalysts:
        symbol = str(catalyst.get("symbol") or "").upper()
        if not symbol:
            continue
        by_symbol.setdefault(symbol, {"symbol": symbol}).setdefault("upcoming_catalysts", []).append(catalyst)
    rows = list(by_symbol.values())
    rows.sort(
        key=lambda row: (
            bool(row.get("upcoming_catalysts")),
            bool(row.get("jenny_review")),
            abs(_num(row.get("current_value")) or 0.0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _human_positions(snapshot: dict[str, Any]) -> str:
    lines = [
        f"Portfolio ${float(snapshot.get('total_value') or 0):,.0f}; "
        f"{snapshot.get('num_positions')} positions; quotes {snapshot.get('quote_freshness_label') or snapshot.get('quote_freshness_status') or 'unknown'}",
        "",
    ]
    for row in snapshot.get("positions", []):
        weight = row.get("weight_pct")
        gain_pct = row.get("gain_pct")
        lines.append(
            f"  - {row.get('symbol')}: ${float(row.get('current_value') or 0):,.0f}"
            f" ({weight if weight is not None else '?'}% weight, gain {gain_pct if gain_pct is not None else '?'}%)"
        )
    return "\n".join(lines)


def _human_briefing_context(data: dict[str, Any]) -> str:
    lines = [_human_positions(data.get("portfolio") or {}), "", "Pulse impact watchlist:"]
    for row in data.get("impact_watchlist", []):
        bits = []
        if row.get("upcoming_catalysts"):
            bits.append(f"{len(row['upcoming_catalysts'])} catalyst(s)")
        if row.get("jenny_review"):
            bits.append(f"Jenny {row['jenny_review'].get('final_verdict')}")
        if row.get("weight_pct") is not None:
            bits.append(f"{row.get('weight_pct')}% weight")
        lines.append(f"  - {row.get('symbol')}: " + (", ".join(bits) if bits else "position context only"))
    return "\n".join(lines)


def _scope_klass(value: Any) -> Any:
    """Friendly asset-class label (or raw value if unknown)."""
    return FRIENDLY_CLASS.get(value, value)


def _candidate_lines(row: dict[str, Any]) -> list[str]:
    symbol = row.get("symbol", "?")
    loss = float(row.get("unrealized_loss", 0) or 0)
    loss_pct = float(row.get("unrealized_loss_pct", 0) or 0) * 100
    account = row.get("account_id", "?")
    lines = [f"  - {symbol}: paper loss ${loss:,.2f} ({loss_pct:+.2f}%) in account {account}"]
    if row.get("wash_sale_blocked"):
        reason = row.get("wash_sale_reason") or "recent buys block this sale"
        lines.append(f"      blocked: {reason}")
    replacement = row.get("replacement")
    if isinstance(replacement, dict):
        to_symbol = replacement.get("to_symbol")
        confidence = replacement.get("confidence")
        if to_symbol:
            lines.append(f"      possible replacement: {to_symbol} ({confidence})")
    return lines


def _human_candidates(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No tax-saving sales found."
    lines = [f"Found {len(rows)} sale(s) that could lower this year's taxes:", ""]
    for row in rows:
        lines.extend(_candidate_lines(row))
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


def _candidate_digest(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return _envelope(rows, {"limit": limit}, digest=True)


@app.command("positions")
@usage(
    surface="st.portfolio.positions",
    cmd="st portfolio positions --limit 25",
    when="inspect current held positions and weights before market-aware briefings or portfolio impact analysis",
    precautions=("read-only; uses portfolio-ai API and excludes raw credentials",),
    task_types=("portfolio", "briefing", "market"),
    tier="mandate",
)
def positions(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200, help="Maximum positions to return")] = 25,
    include_paper: Annotated[bool, typer.Option("--include-paper/--no-include-paper", help="Include paper positions")]= False,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Return current portfolio holdings, values, weights, and quote freshness."""
    portfolio = _as_dict(_get(remote, EP_PORTFOLIO, params={"include_paper": _bool_param(include_paper)}))
    snapshot = _portfolio_position_payload(portfolio, limit=limit)
    envelope = _success_envelope(snapshot, {"limit": limit, "include_paper": include_paper})
    _emit(envelope, human=human, summary_text=_human_positions(snapshot))


@app.command("market-status")
@usage(
    surface="st.portfolio.market-status",
    cmd="st portfolio market-status",
    when="determine current NYSE trading-day/open/closed state for market-specific Pulse runs",
    precautions=("read-only; if portfolio-ai is down do not guess holiday/open status",),
    task_types=("portfolio", "market", "briefing"),
    tier="mandate",
)
def market_status(
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Return portfolio-ai's market calendar/status contract."""
    data = _as_dict(_get(remote, EP_MARKET_STATUS))
    envelope = _success_envelope(data, {})
    text = (
        f"Market {data.get('status')} at {data.get('current_time_et')}; "
        f"last_trading_day={data.get('last_trading_day')} next_trading_day={data.get('next_trading_day')}"
    )
    _emit(envelope, human=human, summary_text=text)


@app.command("briefing-context")
@usage(
    surface="st.portfolio.briefing-context",
    cmd="st portfolio briefing-context --limit 25 --catalyst-days 14",
    when="gather portfolio-aware context for Pulse agents so market news can be tied to held positions and likely impact",
    precautions=("read-only; outputs context and watchlist, not investment advice or trade execution",),
    task_types=("portfolio", "briefing", "market"),
    tier="mandate",
)
def briefing_context(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200, help="Maximum positions/watchlist rows")] = 25,
    catalyst_days: Annotated[int, typer.Option("--catalyst-days", min=1, max=365, help="Upcoming catalyst lookahead")] = 14,
    include_jenny: Annotated[bool, typer.Option("--include-jenny/--no-include-jenny", help="Include Jenny position review context")] = True,
    include_paper: Annotated[bool, typer.Option("--include-paper/--no-include-paper", help="Include paper positions")]= False,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Compose holdings, analytics, catalysts, Jenny reviews, and market status for Pulse."""
    portfolio_raw = _as_dict(_get(remote, EP_PORTFOLIO, params={"include_paper": _bool_param(include_paper)}))
    portfolio = _portfolio_position_payload(portfolio_raw, limit=limit)
    symbols = {str(row.get("symbol") or "").upper() for row in portfolio.get("positions", []) if row.get("symbol")}
    analytics = _as_dict(_get(remote, EP_PORTFOLIO_ANALYTICS, params={"include_paper": _bool_param(include_paper)}))
    market = _as_dict(_get(remote, EP_MARKET_STATUS))
    catalysts_data = _as_dict(_get(remote, EP_CATALYSTS, params={"days": catalyst_days, "limit": min(200, max(limit * 2, 20)), "include_watchlist": "true", "detail": "true"}))
    catalysts = [row for row in _as_list(catalysts_data.get("catalysts")) if str(row.get("symbol") or "").upper() in symbols]
    jenny = _as_dict(_get(remote, EP_PORTFOLIO_JENNY)) if include_jenny else {}
    jenny_views = _jenny_position_views(jenny, symbols) if include_jenny else []
    data = {
        "portfolio": portfolio,
        "market_status": market,
        "analytics": {
            "portfolio_beta": analytics.get("portfolio_beta"),
            "portfolio_volatility": analytics.get("portfolio_volatility"),
            "sharpe_ratio": analytics.get("sharpe_ratio"),
            "sector_exposure": analytics.get("sector_exposure"),
            "risk_profile": analytics.get("risk_profile"),
            "diversification_score": analytics.get("diversification_score"),
            "top_performers": (analytics.get("top_performers") or [])[:5],
            "bottom_performers": (analytics.get("bottom_performers") or [])[:5],
        },
        "position_reviews": jenny_views,
        "position_catalysts": catalysts,
        "impact_watchlist": _impact_watchlist(portfolio.get("positions", []), jenny_views, catalysts, limit=limit),
        "agent_instruction": "Use this context to predict likely directional/volatility impact of briefing items on held positions. Treat predictions as probabilistic analysis, not trading advice.",
    }
    envelope = _success_envelope(data, {"limit": limit, "catalyst_days": catalyst_days, "include_jenny": include_jenny, "include_paper": include_paper})
    _emit(envelope, human=human, summary_text=_human_briefing_context(data))


_ACCOUNT_FIELDS = (
    "label",
    "asset_group",
    "account_type",
    "institution_name",
    "owner_name",
    "current_value",
    "balance",
    "valuation_source",
    "freshness_status",
    "freshness_label",
    "days_since_balance",
    "last_balance_at",
    "match_status",
    "gap_flags",
)

_BUDGET_CATEGORY_FIELDS = (
    "category",
    "essentiality",
    "total_spend",
    "average_monthly_spend",
    "share_of_spend",
    "found_monthly_budget",
    "confirmed_monthly_budget",
    "budget_source",
    "budget_status",
)


@app.command("household")
@usage(
    surface="st.portfolio.household",
    cmd="st portfolio household",
    when="answer household money questions: net worth, asset/liability totals, account-control trust status",
    precautions=("read-only; uses portfolio-ai API and excludes raw credentials",),
    task_types=("portfolio", "household", "advisor"),
    tier="reference",
)
def household(
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Return household net worth, asset totals, and account-control status."""
    dashboard = _as_dict(_get(remote, EP_HOUSEHOLD_DASHBOARD))
    overview = _as_dict(dashboard.get("overview"))
    control = _as_dict(dashboard.get("account_control"))
    data = {"generated_at": dashboard.get("generated_at"), "overview": overview, "account_control": control}
    envelope = _success_envelope(data, {})
    text = (
        f"Net worth ${_num(overview.get('net_worth')) or 0:,.0f}; "
        f"tracked accounts {overview.get('tracked_account_count')}; "
        f"account control {control.get('status')} ({control.get('issue_count')} issue(s))"
    )
    _emit(envelope, human=human, summary_text=text)


@app.command("accounts")
@usage(
    surface="st.portfolio.accounts",
    cmd="st portfolio accounts",
    when="list household accounts with balances and data-freshness flags before trusting totals or diagnosing stale accounts",
    precautions=("read-only; uses portfolio-ai API and excludes raw credentials",),
    task_types=("portfolio", "household", "advisor"),
    tier="reference",
)
def accounts(
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Return household accounts with balances and freshness flags."""
    dashboard = _as_dict(_get(remote, EP_HOUSEHOLD_DASHBOARD))
    rows = [
        {field: row.get(field) for field in _ACCOUNT_FIELDS}
        for row in _as_list(dashboard.get("accounts"))
    ]
    stale = sum(1 for row in rows if row.get("freshness_status") not in (None, "fresh"))
    envelope = _success_envelope(rows, {"count": len(rows), "stale_count": stale})
    total = sum(_num(row.get("current_value")) or 0.0 for row in rows)
    _emit(envelope, human=human, summary_text=f"{len(rows)} account(s) totalling ${total:,.0f}; {stale} not fresh")


@app.command("budget")
@usage(
    surface="st.portfolio.budget",
    cmd="st portfolio budget",
    when="answer spending questions: budget categories, spend pace, income, savings rate",
    precautions=("read-only; uses portfolio-ai API and excludes raw credentials",),
    task_types=("portfolio", "household", "advisor"),
    tier="reference",
)
def budget(
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Return budget summary, category spend pace, and savings rate."""
    spending = _as_dict(_get(remote, EP_HOUSEHOLD_SPENDING))
    summary = _as_dict(spending.get("summary"))
    categories = [
        {field: row.get(field) for field in _BUDGET_CATEGORY_FIELDS}
        for row in _as_list(spending.get("categories"))
    ]
    data = {
        "generated_at": spending.get("generated_at"),
        "summary": summary,
        "categories": categories,
        "monthly_trend": _as_list(spending.get("monthly_trend")),
    }
    envelope = _success_envelope(data, {"category_count": len(categories)})
    text = (
        f"{summary.get('timeframe_label')}: avg monthly spend ${_num(summary.get('average_monthly_spend')) or 0:,.0f}; "
        f"{summary.get('over_budget_count')} category(ies) over budget; savings_rate={summary.get('savings_rate')}"
    )
    _emit(envelope, human=human, summary_text=text)


@app.command("symbol-intel")
@usage(
    surface="st.portfolio.symbol-intel",
    cmd="st portfolio symbol-intel AAPL",
    when="answer questions about a specific stock: scores, signal, quote, news, portfolio context, recommendation",
    precautions=("read-only; probabilistic analysis, not trading advice or trade execution",),
    task_types=("portfolio", "market", "advisor"),
    tier="reference",
)
def symbol_intel(
    symbol: Annotated[str, typer.Argument(help="Ticker symbol, e.g. AAPL")],
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Return the full symbol intelligence snapshot for one ticker."""
    ticker = symbol.strip().upper()
    data = _as_dict(_get(remote, EP_SYMBOL_INTELLIGENCE.format(symbol=ticker)))
    envelope = _success_envelope(data, {"symbol": ticker})
    scores = _as_dict(data.get("scores"))
    text = f"{ticker}: signal={scores.get('signal_type')} overall={_num(scores.get('overall')) or 0:.1f}"
    _emit(envelope, human=human, summary_text=text)


@app.command("macro")
@usage(
    surface="st.portfolio.macro",
    cmd="st portfolio macro",
    when="check macro deployment gate and market-conditions snapshot before deployment or market-timing questions",
    precautions=("read-only; probabilistic market read, not trading advice",),
    task_types=("portfolio", "market", "advisor"),
    tier="reference",
)
def macro(
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Return the L1 macro deployment-gate / market-conditions snapshot."""
    data = _as_dict(_get(remote, EP_MACRO_CONDITIONS))
    envelope = _success_envelope(data, {})
    text = (
        f"Macro {data.get('state')} (zone={data.get('macro_zone')}); "
        f"deployment_score={data.get('deployment_score')}; {data.get('overall_read')}"
    )
    _emit(envelope, human=human, summary_text=text)


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
    params = {
        "limit": limit,
        "min_loss": min_loss,
        "min_loss_pct": min_loss_pct,
        "detail": _bool_param(detail),
    }
    rows = _as_list(_get(remote, EP_TLH_CANDIDATES, params=params))
    if summary:
        digest = _candidate_digest(rows, limit)
        _emit(
            digest,
            human=human,
            summary_text=(
                f"{digest['data']['count']} candidate(s); "
                f"total paper loss ${digest['data']['total_loss']:,.2f}; "
                f"{digest['data']['blocked_count']} blocked by recent buys"
            ),
        )
        return
    envelope = _success_envelope(rows, {"count": len(rows), "limit": limit, "next_cursor": None})
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
    verdict = _as_dict(_post_or_put(remote, EP_TLH_WASHSALE, json_body=body))
    envelope = _success_envelope(verdict, {"symbol": symbol, "sell_date": sell_date})
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
    spec = _as_dict(_get(remote, EP_OPENAPI))
    if not spec:
        output_error("portfolio-ai /openapi.json did not return a JSON object")
        raise typer.Exit(1)

    paths = spec.get("paths", {})
    operation = paths.get(path, {}).get(method)
    if not isinstance(operation, dict):
        output_error(f"openapi spec has no {method.upper()} {path}")
        raise typer.Exit(1)

    response = (
        operation.get("responses", {})
        .get(HTTP_OK, {})
        .get("content", {})
        .get(JSON_CONTENT_TYPE, {})
    )
    schema_obj = response.get("schema") or {}
    components = spec.get("components", {}).get("schemas", {})
    output_json({"command": command, "path": path, "method": method.upper(), "schema": schema_obj, "components": components})


# ----------------------------------------------------------------------
# IPS / drift / rebalance — F3 surface
# ----------------------------------------------------------------------


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
        klass = _scope_klass(row.get("asset_class"))
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
        lines.append("Held but no goal set: " + ", ".join(_scope_klass(c) for c in missing))
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
        klass = _scope_klass(trade.get("asset_class"))
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
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = DEFAULT_SCOPE,
    summary: Annotated[bool, typer.Option("--summary/--no-summary", help="Compact digest (default) vs full row table")] = True,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Show how far each asset class is from its goal allocation.

    Default response is a single-line digest. Pass ``--no-summary`` for
    the full per-class table.
    """
    _require_scope(scope)
    params = {"scope": scope, "scope_id": scope_id, "summary": _bool_param(summary)}
    data = _as_dict(_get(remote, EP_IPS_DRIFT, params=params))
    envelope = _success_envelope(data, {"scope": scope, "scope_id": scope_id, "summary": summary})
    summary_text = _human_drift_summary(data) if summary else _human_drift_report(data)
    _emit(envelope, human=human, summary_text=summary_text)


@app.command("rebalance")
def rebalance(
    scope: Annotated[str, typer.Option("--scope", help="household | account")] = "household",
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = DEFAULT_SCOPE,
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
    _require_scope(scope)
    body = {
        "scope": scope,
        "scope_id": scope_id,
        "prefer_tax_advantaged": prefer_tax_advantaged,
        "prefer_ltcg": prefer_ltcg,
    }
    plan = _as_dict(_post_or_put(remote, EP_IPS_REBALANCE, json_body=body))
    envelope = _success_envelope(plan, {"scope": scope, "scope_id": scope_id})
    _emit(envelope, human=human, summary_text=_human_rebalance_plan(plan))


@ips_app.command("list")
def ips_list(
    scope: Annotated[str, typer.Option("--scope", help="household | account")] = "household",
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = DEFAULT_SCOPE,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """List allocation goals for one scope."""
    _require_scope(scope)
    params = {"scope": scope, "scope_id": scope_id}
    rows = _as_list(_get(remote, EP_IPS_TARGETS, params=params))
    envelope = _success_envelope(rows, {"count": len(rows), "scope": scope, "scope_id": scope_id})
    if human:
        if not rows:
            text = "No allocation goals set yet."
        else:
            lines = ["Allocation goals:"]
            for row in rows:
                klass = _scope_klass(row.get("asset_class"))
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
    scope_id: Annotated[str, typer.Option("--scope-id", help="Scope identifier")] = DEFAULT_SCOPE,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Set or update one allocation goal (upsert)."""
    _require_scope(scope)
    body = {
        "scope": scope,
        "scope_id": scope_id,
        "asset_class": asset_class,
        "target_pct": target,
        "drift_band_pct": band,
        "notes": notes,
    }
    row = _as_dict(_post_or_put(remote, EP_IPS_TARGETS, json_body=body, method="put"))
    envelope = _success_envelope(row, {"upsert": True})
    if human:
        klass = _scope_klass(asset_class)
        text = f"Set {klass} goal to {target * 100:.1f}% (wiggle room ±{band * 100:.1f}%)."
        _emit(envelope, human=True, summary_text=text)
    else:
        _emit(envelope, human=False)


# ----------------------------------------------------------------------
# Catalysts — F4 surface
# ----------------------------------------------------------------------


def _human_catalysts(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No upcoming events in the requested window."
    lines = [f"{len(rows)} upcoming event(s):", ""]
    for row in rows:
        raw_kind = row.get("kind") or ""
        kind = FRIENDLY_KIND.get(raw_kind, raw_kind)
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
    params = {
        "days": days,
        "limit": limit,
        "include_watchlist": _bool_param(include_watchlist),
        "detail": _bool_param(detail),
    }
    if kinds:
        params["kinds"] = kinds
    if symbols:
        params["symbols"] = symbols
    data = _as_dict(_get(remote, EP_CATALYSTS, params=params))
    rows = data.get("catalysts") or []
    envelope = _success_envelope(data, {"count": len(rows), "limit": limit, "days": days})
    _emit(envelope, human=human, summary_text=_human_catalysts(rows))


# ----------------------------------------------------------------------
# Retirement Monte Carlo — F5 surface
# ----------------------------------------------------------------------


def _human_retirement_summary(summary: dict[str, Any]) -> str:
    success = float(summary.get("success_probability", 0) or 0) * 100
    median = float(summary.get("median_ending_balance", 0) or 0)
    sor = float(summary.get("sequence_of_returns_risk", 0) or 0) * 100
    trials = int(summary.get("trial_count", 0) or 0)
    name = summary.get("name", "scenario")
    lines = [
        f"{name}",
        f"  Probability of having enough: {success:.1f}% (across {trials:,} simulated futures)",
        f"  Median money left at year {summary.get('horizon_years_label', 'end')}: ${median:,.0f}",
        f"  Risk of bad timing early in retirement: {sor:.1f}%",
    ]
    return "\n".join(lines)


def _human_retirement_show(results: dict[str, Any]) -> str:
    summary = results.get("summary") or {}
    inputs = results.get("inputs") or {}
    percentiles = results.get("percentiles") or {}
    lines = [
        _human_retirement_summary(summary),
        "",
        f"Inputs: ${float(inputs.get('portfolio_value', 0) or 0):,.0f} portfolio, "
        f"${float(inputs.get('annual_expenses', 0) or 0):,.0f}/yr spend, "
        f"retire at {inputs.get('retirement_age')}, "
        f"horizon {inputs.get('horizon_years')} years",
        "",
        "Where you might land at the end:",
    ]
    for label in ("p10", "p25", "p50", "p75", "p90"):
        if label in percentiles:
            lines.append(
                f"  {label.upper()}: ${float(percentiles[label]):,.0f}"
            )
    return "\n".join(lines)


@retirement_app.command("run")
def retirement_run(
    household_id: Annotated[str, typer.Option("--household-id", help="Household scope identifier")],
    trials: Annotated[int, typer.Option("--trials", min=1, max=50_000, help="Number of simulated futures")] = 10_000,
    name: Annotated[str | None, typer.Option("--name", help="Scenario label (auto-generated if omitted)")] = None,
    seed: Annotated[int | None, typer.Option("--seed", help="Deterministic random seed")] = None,
    annual_expenses: Annotated[float | None, typer.Option("--annual-expenses", min=0.0, help="Override annual spend in dollars")] = None,
    retirement_age: Annotated[int | None, typer.Option("--retirement-age", min=18, max=120, help="Override target retirement age")] = None,
    horizon_years: Annotated[int | None, typer.Option("--horizon-years", min=1, max=70, help="Override projection horizon")] = None,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Run + persist one retirement Monte Carlo scenario.

    Stress tests the household plan across ``--trials`` simulated
    futures (default 10,000; capped at 50,000). Pass ``--seed N`` for
    a reproducible run.
    """
    body: dict[str, Any] = {"household_id": household_id, "trials": trials}
    if name is not None:
        body["name"] = name
    if seed is not None:
        body["seed"] = seed
    if annual_expenses is not None:
        body["annual_expenses"] = annual_expenses
    if retirement_age is not None:
        body["retirement_age"] = retirement_age
    if horizon_years is not None:
        body["horizon_years"] = horizon_years
    results = _as_dict(_post_or_put(remote, EP_RETIREMENT_SCENARIOS, json_body=body))
    envelope = _success_envelope(results, {"household_id": household_id, "trials": trials})
    _emit(envelope, human=human, summary_text=_human_retirement_show(results))


@retirement_app.command("list")
def retirement_list(
    household_id: Annotated[str, typer.Option("--household-id", help="Household scope identifier")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=100, help="Maximum scenarios to return")] = 20,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """List recent retirement scenarios for one household."""
    params = {"household_id": household_id, "limit": limit}
    rows = _as_list(_get(remote, EP_RETIREMENT_SCENARIOS, params=params))
    envelope = _success_envelope(rows, {"count": len(rows), "limit": limit, "household_id": household_id})
    if human:
        if not rows:
            text = f"No retirement scenarios saved for household {household_id}."
        else:
            blocks = [_human_retirement_summary(row) for row in rows]
            text = "\n\n".join(blocks)
        _emit(envelope, human=True, summary_text=text)
    else:
        _emit(envelope, human=False)


@retirement_app.command("show")
def retirement_show(
    scenario_id: Annotated[str, typer.Argument(help="Scenario UUID returned by run/list")],
    detail: Annotated[bool, typer.Option("--detail", help="Include percentile paths and CMA snapshot")] = False,
    human: Annotated[bool, typer.Option("--human", help="Plain-English rendering")] = False,
    remote: Annotated[bool, typer.Option("--remote", help="Use production hosts.production_api endpoint")] = False,
) -> None:
    """Show one retirement scenario by id."""
    params = {"detail": _bool_param(detail)}
    results = _as_dict(_get(remote, f"{EP_RETIREMENT_SCENARIOS}/{scenario_id}", params=params))
    envelope = _success_envelope(results, {"scenario_id": scenario_id, "detail": detail})
    _emit(envelope, human=human, summary_text=_human_retirement_show(results))
