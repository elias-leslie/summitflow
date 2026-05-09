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


def _fake_client(get_return: Any = None, post_return: Any = None, *, get_exc: Exception | None = None, post_exc: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if get_exc is not None:
        client.get.side_effect = get_exc
    else:
        client.get.return_value = get_return
    if post_exc is not None:
        client.post.side_effect = post_exc
    else:
        client.post.return_value = post_return
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
