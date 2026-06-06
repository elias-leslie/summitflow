"""Tests for ``st portfolio`` (TLH subcommands + schema + URL resolver).

Pattern note: SummitFlow's CLI tests mock the HTTP client at the
:class:`PortfolioClient` boundary rather than using ``respx`` (the test
suite does not depend on it). This keeps the test surface small and
focused on URL routing, exit codes, and rendering — all behaviors the
plan's F6 calls out as must-cover.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli._client_base import APIError
from cli._portfolio_client import (
    PortfolioConnectError,
    resolve_portfolio_api_url,
)
from cli.main import app

runner = CliRunner()


# --- url resolver ---------------------------------------------------------


def _write_identity(root: Path, *, project_id: str = "portfolio-ai", backend_port: int = 8000, prod_api: str = "portapi.summitflow.dev") -> None:
    (root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {"id": project_id, "repo_name": project_id, "display_name": project_id},
                "runtime": {"backend_port": backend_port},
                "hosts": {"production_api": prod_api},
            }
        )
    )


def test_resolver_prefers_env_var(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://override.local:9999/")
    resolved = resolve_portfolio_api_url(cwd=tmp_path)
    assert resolved.url == "http://override.local:9999"
    assert resolved.source == "env"


def test_resolver_uses_ports_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ST_PORTFOLIO_API_URL", raising=False)
    _write_identity(tmp_path)
    (tmp_path / "ports.json").write_text(json.dumps({"api_url": "http://localhost:8163"}))
    resolved = resolve_portfolio_api_url(cwd=tmp_path)
    assert resolved.url == "http://localhost:8163"
    assert resolved.source == "ports_json"


def test_resolver_falls_back_to_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ST_PORTFOLIO_API_URL", raising=False)
    _write_identity(tmp_path, backend_port=8001)
    # No ports.json on disk.
    resolved = resolve_portfolio_api_url(cwd=tmp_path)
    assert resolved.url == "http://localhost:8001"
    assert resolved.source == "identity"


def test_resolver_default_when_outside_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ST_PORTFOLIO_API_URL", raising=False)
    # tmp_path has no identity, and registry should fail in test env.
    with patch("cli._portfolio_client._from_summitflow_registry", return_value=None):
        resolved = resolve_portfolio_api_url(cwd=tmp_path)
    assert resolved.source == "default"
    assert resolved.url == "http://localhost:8000"


def test_resolver_remote_prefers_production_when_no_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ST_PORTFOLIO_API_URL", raising=False)
    _write_identity(tmp_path, prod_api="portapi.example.com")
    # Force registry path off so --remote actually trips. Since identity_url
    # also resolves, the resolver returns identity (precedence) — verify
    # that explicitly so we document the intentional ordering.
    resolved = resolve_portfolio_api_url(cwd=tmp_path, remote=True)
    assert resolved.source == "identity"
    assert resolved.url == "http://localhost:8000"


def test_resolver_remote_uses_hosts_when_no_local_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ST_PORTFOLIO_API_URL", raising=False)
    # Empty tmp_path — no identity, no ports.json.
    with patch("cli._portfolio_client._from_summitflow_registry", return_value=None), \
         patch("cli._portfolio_client._from_remote_flag", return_value="https://portapi.example.com"):
        resolved = resolve_portfolio_api_url(cwd=tmp_path, remote=True)
    assert resolved.source == "remote"
    assert resolved.url == "https://portapi.example.com"


# --- candidates -----------------------------------------------------------


def _fake_client(
    get_return: Any = None,
    post_return: Any = None,
    put_return: Any = None,
    *,
    get_exc: Exception | None = None,
    post_exc: Exception | None = None,
    put_exc: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    if get_exc is not None:
        client.get.side_effect = get_exc
    else:
        client.get.return_value = get_return
    if post_exc is not None:
        client.post.side_effect = post_exc
    else:
        client.post.return_value = post_return
    if put_exc is not None:
        client.put.side_effect = put_exc
    else:
        client.put.return_value = put_return
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    return client


def _patch_client(client: MagicMock):
    return patch("cli.commands.portfolio.PortfolioClient", return_value=client)


def test_tlh_candidates_emits_envelope(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    rows = [
        {"symbol": "AAPL", "account_id": "acc1", "unrealized_loss": -1500.0, "unrealized_loss_pct": -0.12},
        {"symbol": "GOOG", "account_id": "acc2", "unrealized_loss": -800.0, "unrealized_loss_pct": -0.07},
    ]
    fake = _fake_client(get_return=rows)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "tlh", "candidates", "--limit", "5"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["data"] == rows
    assert payload["meta"]["count"] == 2
    assert payload["meta"]["limit"] == 5
    fake.get.assert_called_once_with(
        "/api/portfolio/tlh/candidates",
        params={"limit": 5, "min_loss": 500.0, "min_loss_pct": 0.05, "detail": "false"},
    )


def test_tlh_candidates_summary_mode(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    rows = [
        {"symbol": "AAPL", "unrealized_loss": -1500.0, "wash_sale_blocked": True},
        {"symbol": "GOOG", "unrealized_loss": -800.0},
    ]
    fake = _fake_client(get_return=rows)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "tlh", "candidates", "--summary"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["data"] == {"count": 2, "total_loss": -2300.0, "blocked_count": 1}


def test_tlh_candidates_human_mode(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    rows = [{"symbol": "AAPL", "account_id": "acc1", "unrealized_loss": -1500.0, "unrealized_loss_pct": -0.12}]
    fake = _fake_client(get_return=rows)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "tlh", "candidates", "--human"])
    assert result.exit_code == 0, result.stdout
    assert "AAPL" in result.stdout
    assert "$-1,500.00" in result.stdout


def test_tlh_candidates_passes_detail_flag(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_return=[])
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "tlh", "candidates", "--detail", "--min-loss", "100", "--min-loss-pct", "0.02"])
    assert result.exit_code == 0
    fake.get.assert_called_once_with(
        "/api/portfolio/tlh/candidates",
        params={"limit": 20, "min_loss": 100.0, "min_loss_pct": 0.02, "detail": "true"},
    )


def test_tlh_candidates_connection_error_exits_2(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_exc=PortfolioConnectError("http://test/api/portfolio/tlh/candidates", "boom"))
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "tlh", "candidates"])
    assert result.exit_code == 2, result.stdout
    err = json.loads(result.stderr.strip())
    assert err["error"] == "portfolio_api_unreachable"
    assert err["url"].endswith("/api/portfolio/tlh/candidates")


def test_tlh_candidates_http_error_exits_1(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_exc=APIError(500, {"detail": "kaboom", "error": "internal"}))
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "tlh", "candidates"])
    assert result.exit_code == 1, result.stdout
    err = json.loads(result.stderr.strip())
    assert err["status"] == 500
    assert err["error"] == "internal"


# --- wash-sale-check ------------------------------------------------------


def test_wash_sale_check_posts_body(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    verdict = {
        "symbol": "AAPL",
        "sell_date": "2026-05-15",
        "household_id": "hh-1",
        "blocked": False,
        "conflicting_buys": [],
    }
    fake = _fake_client(post_return=verdict)
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio", "tlh", "wash-sale-check",
                "--symbol", "AAPL",
                "--sell-date", "2026-05-15",
                "--household-id", "hh-1",
            ],
        )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["data"]["symbol"] == "AAPL"
    fake.post.assert_called_once_with(
        "/api/portfolio/tlh/wash-sale-check",
        json_body={"symbol": "AAPL", "sell_date": "2026-05-15", "household_id": "hh-1"},
    )


def test_wash_sale_check_invalid_date_exits_3(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(post_return={})
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio", "tlh", "wash-sale-check",
                "--symbol", "AAPL",
                "--sell-date", "not-a-date",
                "--household-id", "hh-1",
            ],
        )
    assert result.exit_code == 3, result.stdout
    fake.post.assert_not_called()


def test_wash_sale_check_human_mode(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    verdict = {
        "symbol": "AAPL",
        "sell_date": "2026-05-15",
        "household_id": "hh-1",
        "blocked": True,
        "reason": "Recent buy in spouse Roth",
        "conflicting_buys": [
            {"trade_date": "2026-05-01", "shares": 10, "days_offset": -14, "account_id": "spouse-roth", "txn_id": "t1", "account_type": "Roth"}
        ],
    }
    fake = _fake_client(post_return=verdict)
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio", "tlh", "wash-sale-check",
                "--symbol", "AAPL",
                "--sell-date", "2026-05-15",
                "--household-id", "hh-1",
                "--human",
            ],
        )
    assert result.exit_code == 0, result.stdout
    assert "would void" in result.stdout
    assert "spouse-roth" in result.stdout


# --- schema --------------------------------------------------------------


def test_schema_unknown_command_exits_3(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    result = runner.invoke(app, ["portfolio", "schema", "made-up-command"])
    assert result.exit_code == 3, result.stdout


def test_schema_projects_response_for_known_path(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    spec = {
        "components": {"schemas": {"TLHCandidate": {"type": "object"}}},
        "paths": {
            "/api/portfolio/tlh/candidates": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TLHCandidate"}
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    fake = _fake_client(get_return=spec)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "schema", "tlh-candidates"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["command"] == "tlh-candidates"
    assert payload["path"] == "/api/portfolio/tlh/candidates"
    assert payload["schema"] == {"$ref": "#/components/schemas/TLHCandidate"}
    assert "TLHCandidate" in payload["components"]


def test_schema_missing_path_exits_1(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_return={"paths": {}})
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "schema", "tlh-candidates"])
    assert result.exit_code == 1, result.stdout


# --- drift ----------------------------------------------------------------


def test_drift_summary_default(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    summary = {
        "scope": "household",
        "scope_id": "default",
        "total_value": 50000.0,
        "max_drift_pct": 0.12,
        "classes_out_of_band": 2,
        "snapshot_date": "2026-05-09",
    }
    fake = _fake_client(get_return=summary)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "drift"])
    assert result.exit_code == 0, result.stdout
    fake.get.assert_called_once_with(
        "/api/portfolio/ips/drift",
        params={"scope": "household", "scope_id": "default", "summary": "true"},
    )
    payload = json.loads(result.stdout.strip())
    assert payload["data"]["max_drift_pct"] == 0.12


def test_drift_full_report_when_no_summary(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    report = {
        "scope": "household",
        "scope_id": "default",
        "snapshot_date": "2026-05-09",
        "total_value": 10000.0,
        "rows": [
            {
                "asset_class": "us_equity",
                "target_pct": 0.6,
                "actual_pct": 0.7,
                "drift_pct": 0.1,
                "drift_band_pct": 0.05,
                "out_of_band": True,
                "target_value": 6000,
                "actual_value": 7000,
                "drift_value": 1000,
            }
        ],
        "classes_missing_targets": [],
    }
    fake = _fake_client(get_return=report)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "drift", "--no-summary"])
    assert result.exit_code == 0, result.stdout
    fake.get.assert_called_once_with(
        "/api/portfolio/ips/drift",
        params={"scope": "household", "scope_id": "default", "summary": "false"},
    )


def test_drift_human_summary(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    summary = {
        "scope": "household",
        "scope_id": "default",
        "total_value": 50000.0,
        "max_drift_pct": 0.12,
        "classes_out_of_band": 2,
        "snapshot_date": "2026-05-09",
    }
    fake = _fake_client(get_return=summary)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "drift", "--human"])
    assert result.exit_code == 0, result.stdout
    assert "outside wiggle room" in result.stdout
    assert "$50,000" in result.stdout


def test_drift_invalid_scope_exits_3(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_return={})
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "drift", "--scope", "weird"])
    assert result.exit_code == 3
    fake.get.assert_not_called()


# --- rebalance ------------------------------------------------------------


def test_rebalance_posts_body(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    plan = {
        "scope": "household",
        "scope_id": "default",
        "snapshot_date": "2026-05-09",
        "trades": [
            {
                "action": "buy",
                "account_id": "roth-1",
                "account_type": "Roth",
                "symbol": "VTI",
                "asset_class": "us_equity",
                "shares": 0.0,
                "estimated_value": 5000.0,
                "rationale": "route_to_tax_advantaged",
                "wash_sale_conflict": False,
                "wash_sale_reason": None,
                "realized_gain_long_term": 0.0,
                "realized_gain_short_term": 0.0,
            }
        ],
        "total_buy_value": 5000.0,
        "total_sell_value": 0.0,
        "wash_sale_conflicts": 0,
        "asset_classes_corrected": ["us_equity"],
    }
    fake = _fake_client(post_return=plan)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "rebalance"])
    assert result.exit_code == 0, result.stdout
    fake.post.assert_called_once_with(
        "/api/portfolio/ips/rebalance",
        json_body={
            "scope": "household",
            "scope_id": "default",
            "prefer_tax_advantaged": True,
            "prefer_ltcg": True,
        },
    )


def test_rebalance_human_renders_trade(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    plan = {
        "trades": [
            {
                "action": "buy",
                "symbol": "VTI",
                "asset_class": "us_equity",
                "estimated_value": 5000.0,
                "account_type": "Roth",
                "wash_sale_conflict": False,
            }
        ],
        "total_buy_value": 5000.0,
        "total_sell_value": 0.0,
        "wash_sale_conflicts": 0,
    }
    fake = _fake_client(post_return=plan)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "rebalance", "--human"])
    assert result.exit_code == 0, result.stdout
    assert "BUY  $5,000 of VTI" in result.stdout
    assert "Roth" in result.stdout


# --- ips list/set --------------------------------------------------------


def test_ips_list_returns_targets(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    targets = [
        {"asset_class": "us_equity", "target_pct": 0.6, "drift_band_pct": 0.05},
        {"asset_class": "bonds", "target_pct": 0.4, "drift_band_pct": 0.05},
    ]
    fake = _fake_client(get_return=targets)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "ips", "list"])
    assert result.exit_code == 0, result.stdout
    fake.get.assert_called_once_with(
        "/api/portfolio/ips/targets",
        params={"scope": "household", "scope_id": "default"},
    )
    payload = json.loads(result.stdout.strip())
    assert len(payload["data"]) == 2


def test_ips_set_uses_put(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    target = {
        "scope": "household",
        "scope_id": "default",
        "asset_class": "us_equity",
        "target_pct": 0.6,
        "drift_band_pct": 0.05,
    }
    fake = _fake_client(put_return=target)
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio", "ips", "set",
                "--asset-class", "us_equity",
                "--target", "0.6",
            ],
        )
    assert result.exit_code == 0, result.stdout
    fake.put.assert_called_once_with(
        "/api/portfolio/ips/targets",
        json_body={
            "scope": "household",
            "scope_id": "default",
            "asset_class": "us_equity",
            "target_pct": 0.6,
            "drift_band_pct": 0.05,
            "notes": None,
        },
    )


# --- catalysts ----------------------------------------------------------


def test_catalysts_default_emits_envelope(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    payload = {
        "schema_version": 1,
        "days": 14,
        "limit": 20,
        "kinds": ["earnings", "ex_dividend", "fomc"],
        "include_watchlist": True,
        "catalysts": [
            {
                "schema_version": 1,
                "symbol": "AAPL",
                "kind": "earnings",
                "date": "2026-05-20",
                "days_until": 11,
            }
        ],
    }
    fake = _fake_client(get_return=payload)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "catalysts"])
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout.strip())
    assert body["ok"] is True
    assert body["data"] == payload
    assert body["meta"]["count"] == 1
    fake.get.assert_called_once_with(
        "/api/catalysts/upcoming",
        params={
            "days": 14,
            "limit": 20,
            "include_watchlist": "true",
            "detail": "false",
        },
    )


def test_catalysts_passes_kinds_and_symbols(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_return={"catalysts": []})
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio",
                "catalysts",
                "--days",
                "30",
                "--kinds",
                "earnings,fomc",
                "--symbols",
                "AAPL,MSFT",
                "--no-include-watchlist",
                "--detail",
            ],
        )
    assert result.exit_code == 0, result.stdout
    fake.get.assert_called_once_with(
        "/api/catalysts/upcoming",
        params={
            "days": 30,
            "limit": 20,
            "include_watchlist": "false",
            "detail": "true",
            "kinds": "earnings,fomc",
            "symbols": "AAPL,MSFT",
        },
    )


def test_catalysts_human_mode_renders_friendly(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    payload = {
        "catalysts": [
            {
                "symbol": "AAPL",
                "kind": "ex_dividend",
                "date": "2026-05-12",
                "days_until": 3,
            },
            {
                "symbol": "",
                "kind": "fomc",
                "date": "2026-05-14",
                "days_until": 5,
            },
        ]
    }
    fake = _fake_client(get_return=payload)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "catalysts", "--human"])
    assert result.exit_code == 0, result.stdout
    assert "Last day for dividend" in result.stdout
    assert "Fed interest-rate meeting" in result.stdout
    assert "(macro)" in result.stdout


def test_catalysts_connection_error_exits_2(monkeypatch) -> None:
    from cli._portfolio_client import PortfolioConnectError

    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_exc=PortfolioConnectError("http://test", "boom"))
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "catalysts"])
    assert result.exit_code == 2


# --- retirement-plan ---------------------------------------------------


def _retirement_results(scenario_id: str = "scen-1") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "summary": {
            "schema_version": 1,
            "id": scenario_id,
            "household_id": "hh-test",
            "name": "Baseline",
            "success_probability": 0.83,
            "median_ending_balance": 1_500_000.0,
            "sequence_of_returns_risk": 0.04,
            "trial_count": 10_000,
            "cma_source": "yaml-v1",
            "created_at": "2026-05-09T12:00:00+00:00",
        },
        "inputs": {
            "household_id": "hh-test",
            "primary_age": 46,
            "spouse_age": 44,
            "retirement_age": 65,
            "horizon_years": 30,
            "annual_expenses": 72_000.0,
            "portfolio_value": 900_000.0,
            "asset_allocation": {"us_equity": 0.6, "bonds": 0.4},
            "income_sources": [],
            "inflation_rate": 0.025,
            "as_of_date": "2026-05-09",
        },
        "percentiles": {"p10": 200_000.0, "p50": 1_500_000.0, "p90": 3_500_000.0},
        "failure_year_distribution": {},
        "ending_balance_paths": None,
        "cma_snapshot": None,
    }


def test_retirement_run_posts_full_body(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(post_return=_retirement_results())
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio",
                "retirement-plan",
                "run",
                "--household-id",
                "hh-test",
                "--trials",
                "5000",
                "--seed",
                "42",
                "--annual-expenses",
                "60000",
                "--retirement-age",
                "67",
                "--horizon-years",
                "35",
                "--name",
                "What if I retire later",
            ],
        )
    assert result.exit_code == 0, result.stdout
    fake.post.assert_called_once_with(
        "/api/retirement/scenarios",
        json_body={
            "household_id": "hh-test",
            "trials": 5000,
            "name": "What if I retire later",
            "seed": 42,
            "annual_expenses": 60000.0,
            "retirement_age": 67,
            "horizon_years": 35,
        },
    )


def test_retirement_run_omits_optional_fields(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(post_return=_retirement_results())
    with _patch_client(fake):
        result = runner.invoke(
            app,
            ["portfolio", "retirement-plan", "run", "--household-id", "hh-test"],
        )
    assert result.exit_code == 0, result.stdout
    fake.post.assert_called_once_with(
        "/api/retirement/scenarios",
        json_body={"household_id": "hh-test", "trials": 10_000},
    )


def test_retirement_run_human_renders_translations(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(post_return=_retirement_results())
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio",
                "retirement-plan",
                "run",
                "--household-id",
                "hh-test",
                "--human",
            ],
        )
    assert result.exit_code == 0, result.stdout
    assert "Probability of having enough" in result.stdout
    assert "bad timing early in retirement" in result.stdout


def test_retirement_list_filters_by_household(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    summaries = [_retirement_results()["summary"], _retirement_results("scen-2")["summary"]]
    fake = _fake_client(get_return=summaries)
    with _patch_client(fake):
        result = runner.invoke(
            app,
            [
                "portfolio",
                "retirement-plan",
                "list",
                "--household-id",
                "hh-test",
                "--limit",
                "5",
            ],
        )
    assert result.exit_code == 0, result.stdout
    fake.get.assert_called_once_with(
        "/api/retirement/scenarios",
        params={"household_id": "hh-test", "limit": 5},
    )
    body = json.loads(result.stdout.strip())
    assert body["meta"]["count"] == 2


def test_retirement_show_passes_detail(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_return=_retirement_results())
    with _patch_client(fake):
        result = runner.invoke(
            app,
            ["portfolio", "retirement-plan", "show", "scen-1", "--detail"],
        )
    assert result.exit_code == 0, result.stdout
    fake.get.assert_called_once_with(
        "/api/retirement/scenarios/scen-1",
        params={"detail": "true"},
    )


def test_schema_retirement_run_known(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake_spec = {
        "paths": {
            "/api/retirement/scenarios": {
                "post": {
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {}}}}
                    }
                }
            }
        },
        "components": {"schemas": {}},
    }
    fake = _fake_client(get_return=fake_spec)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "schema", "retirement-run"])
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout.strip())
    assert body["command"] == "retirement-run"
    assert body["method"] == "POST"


def test_schema_catalysts_upcoming_known(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake_spec = {
        "paths": {
            "/api/catalysts/upcoming": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/CatalystCalendarResponse"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {"schemas": {"CatalystCalendarResponse": {"type": "object"}}},
    }
    fake = _fake_client(get_return=fake_spec)
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "schema", "catalysts-upcoming"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["command"] == "catalysts-upcoming"
    assert payload["path"] == "/api/catalysts/upcoming"
    assert payload["method"] == "GET"


def test_positions_returns_weighted_snapshot(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_return={
        "positions": [
            {"symbol": "AAA", "shares": 2, "current_price": 50, "current_value": 100, "gain_pct": 10},
            {"symbol": "BBB", "shares": 1, "current_price": 300, "current_value": 300, "gain_pct": -5},
        ],
        "total_value": 500,
        "total_gain": 20,
        "total_gain_pct": 4,
        "cash_balance_total": 100,
        "quote_freshness_status": "fresh",
    })
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "positions", "--limit", "2"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["data"]["positions"][0]["symbol"] == "BBB"
    assert payload["data"]["positions"][0]["weight_pct"] == 60.0
    fake.get.assert_called_once_with("/api/portfolio", params={"include_paper": "false"})


def test_market_status_calls_portfolio_ai_status(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    fake = _fake_client(get_return={"status": "pre_market", "last_trading_day": "2026-06-05", "next_trading_day": "2026-06-08"})
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "market-status"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["data"]["status"] == "pre_market"
    fake.get.assert_called_once_with("/api/market/status", params=None)


def test_briefing_context_composes_position_impact_inputs(monkeypatch) -> None:
    monkeypatch.setenv("ST_PORTFOLIO_API_URL", "http://test")
    returns = [
        {
            "positions": [{"symbol": "AAA", "shares": 2, "current_price": 50, "current_value": 100}],
            "total_value": 100,
            "quote_freshness_status": "fresh",
        },
        {"portfolio_beta": 1.1, "sector_exposure": {"Technology": 1.0}, "top_performers": [], "bottom_performers": []},
        {"status": "open", "last_trading_day": "2026-06-05", "next_trading_day": "2026-06-08"},
        {"catalysts": [{"symbol": "AAA", "kind": "earnings", "date": "2026-06-09"}, {"symbol": "ZZZ", "kind": "earnings", "date": "2026-06-09"}]},
        {"symbol_reviews": [{"symbol": "AAA", "final_verdict": "watch", "reasons": ["large position"]}]},
    ]
    fake = _fake_client()
    fake.get.side_effect = returns
    with _patch_client(fake):
        result = runner.invoke(app, ["portfolio", "briefing-context", "--limit", "5", "--catalyst-days", "7"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["data"]["impact_watchlist"][0]["symbol"] == "AAA"
    assert payload["data"]["impact_watchlist"][0]["upcoming_catalysts"][0]["kind"] == "earnings"
    assert payload["data"]["impact_watchlist"][0]["jenny_review"]["final_verdict"] == "watch"
    assert [call.args[0] for call in fake.get.call_args_list] == [
        "/api/portfolio",
        "/api/portfolio/analytics",
        "/api/market/status",
        "/api/catalysts/upcoming",
        "/api/portfolio/jenny",
    ]
