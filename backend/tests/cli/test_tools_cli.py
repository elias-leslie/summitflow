"""Tests for st tools CLI auth and routing."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cli.commands.tools import (
    _api_request,
    _build_internal_headers,
    _format_adoption_compact,
    _format_audit_compact,
    _format_cost_compact,
    _format_status_compact,
    app,
)

runner = CliRunner()


class _DummyClient:
    """Minimal httpx.Client stand-in that captures request headers."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> _DummyClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.response


def _json_response(payload: dict[str, object]) -> httpx.Response:
    request = httpx.Request("GET", "http://agent-hub.test/api/access-control/metrics")
    return httpx.Response(200, json=payload, request=request)


def test_build_internal_headers_reads_env_secret() -> None:
    with patch.dict("cli.commands.tools.os.environ", {"INTERNAL_SERVICE_SECRET": "secret-123"}, clear=True):
        assert _build_internal_headers() == {"X-Agent-Hub-Internal": "secret-123"}


def test_tools_status_requires_internal_secret() -> None:
    with patch.dict("cli.commands.tools.os.environ", {}, clear=True):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "INTERNAL_SERVICE_SECRET is not configured." in result.output


def test_tools_default_shows_operator_catalog_without_internal_secret() -> None:
    with patch.dict("cli.commands.tools.os.environ", {}, clear=True):
        result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "TOOLS_CATALOG[" in result.output
    assert "st claim" in result.output
    assert "st service" in result.output
    assert "st graph" in result.output
    assert "st browser" in result.output


def test_tools_catalog_json_includes_registry_source() -> None:
    result = runner.invoke(app, ["catalog"], obj=None)

    assert result.exit_code == 0
    assert "tool-registry.json" in result.output
    assert "st claim" in result.output
    assert "st graph" in result.output
    assert "st browser" in result.output


def test_api_request_uses_env_backed_internal_header() -> None:
    dummy_client = _DummyClient(
        _json_response(
            {
                "summary": {"total_requests": 1, "avg_latency_ms": 5.0, "success_rate": 100.0},
                "by_endpoint": [],
                "by_tool_type": [],
            }
        )
    )

    with (
        patch.dict("cli.commands.tools.os.environ", {"INTERNAL_SERVICE_SECRET": "secret-123"}, clear=True),
        patch("cli.commands.tools.get_agent_hub_url", return_value="http://agent-hub.test"),
        patch("cli.commands.tools.httpx.Client", return_value=dummy_client),
    ):
        result = _api_request("/api/access-control/metrics", params={"hours": 24, "limit": 10})

    assert result["summary"]["total_requests"] == 1
    assert dummy_client.calls == [
        {
            "url": "http://agent-hub.test/api/access-control/metrics",
            "params": {"hours": 24, "limit": 10},
            "headers": {"X-Agent-Hub-Internal": "secret-123"},
        }
    ]


def test_status_compact_includes_top_tool_names(capsys: pytest.CaptureFixture[str]) -> None:
    _format_status_compact(
        {
            "summary": {"total_requests": 3, "avg_latency_ms": 12.0, "success_rate": 100.0},
            "by_tool_type": [{"tool_type": "cli", "count": 3}],
            "by_tool_name": [
                {
                    "tool_name": "st memory search",
                    "count": 2,
                    "success_rate": 100.0,
                    "avg_latency_ms": 9.0,
                }
            ],
            "by_endpoint": [],
        }
    )

    out = capsys.readouterr().out
    assert "Top tools:" in out
    assert "st memory search  2 reqs  100.0%  9ms" in out


def test_adoption_compact_summarizes_st_wrapper_use(capsys: pytest.CaptureFixture[str]) -> None:
    _format_adoption_compact(
        {
            "window_hours": 24,
            "summary": {
                "shell_tool_events": 10,
                "st_commands": 7,
                "st_command_rate": 70.0,
                "raw_quality_commands": 0,
            },
            "top_st_surfaces": [{"surface": "st check", "count": 4}],
        }
    )

    out = capsys.readouterr().out
    assert "TOOLS_ADOPTION[24h]:shell=10 st=7 st_rate=70.0% raw_quality=0" in out
    assert "st check  4" in out


def test_adoption_command_uses_fetcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cli.commands.tools._fetch_adoption_metrics",
        lambda hours, limit: {
            "window_hours": hours,
            "summary": {
                "shell_tool_events": 5,
                "st_commands": 5,
                "st_command_rate": 100.0,
                "raw_quality_commands": 0,
            },
            "top_st_surfaces": [{"surface": "st search", "count": limit}],
        },
    )

    result = runner.invoke(app, ["adoption", "--hours", "2", "--limit", "3"])

    assert result.exit_code == 0
    assert "TOOLS_ADOPTION[2h]:shell=5 st=5 st_rate=100.0% raw_quality=0" in result.output
    assert "st search  3" in result.output


def test_audit_compact_surfaces_expected_tool_findings(capsys: pytest.CaptureFixture[str]) -> None:
    _format_audit_compact(
        {
            "window_hours": 24,
            "summary": {"finding_groups": 1, "events": 2},
            "findings": [
                {
                    "severity": "high",
                    "finding_type": "raw_quality_tool_bypass",
                    "expected_surface": "st.check",
                    "count": 2,
                    "project_id": "summitflow",
                    "agent_slug": "worker",
                    "examples": ["pytest backend/tests/foo.py"],
                }
            ],
        }
    )

    out = capsys.readouterr().out
    assert "TOOLS_AUDIT[24h]:findings=1 events=2" in out
    assert "raw_quality_tool_bypass|expected=st.check|count=2" in out
    assert "ex: pytest backend/tests/foo.py" in out


def test_audit_command_uses_fetcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cli.commands.tools._fetch_audit_metrics",
        lambda hours, limit, project: {
            "window_hours": hours,
            "project": project,
            "summary": {"finding_groups": 0, "events": 0},
            "findings": [],
        },
    )

    result = runner.invoke(app, ["audit", "--hours", "2", "--limit", "3", "-P", "summitflow"])

    assert result.exit_code == 0
    assert "TOOLS_AUDIT[2h]:findings=0 events=0" in result.output
    assert "No high-confidence tool-governance findings." in result.output


def test_cost_compact_shows_manifest_and_hotspots(capsys: pytest.CaptureFixture[str]) -> None:
    _format_cost_compact(
        {
            "window_hours": 24,
            "manifest_costs": [
                {"density": "core", "task": None, "tokens_approx": 100},
                {"density": "task", "task": "verification", "tokens_approx": 160},
                {"density": "full", "task": None, "tokens_approx": 400},
            ],
            "request_hotspots": [
                {
                    "tool_name": "sdk.complete",
                    "tool_type": "sdk",
                    "requests": 2,
                    "tokens_in": 300,
                    "tokens_out": 50,
                    "success_rate": 100.0,
                }
            ],
            "tool_output_hotspots": [
                {
                    "tool_name": "Bash",
                    "events": 4,
                    "output_tokens_approx": 120,
                    "output_chars": 480,
                }
            ],
        }
    )

    out = capsys.readouterr().out
    assert "manifest_core~100t task(verification)~160t full~400t" in out
    assert "sdk.complete|sdk reqs=2 in=300 out=50 success=100.0%" in out
    assert "Bash events=4 out~120t chars=480" in out


def test_cost_command_uses_fetcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cli.commands.tools._fetch_cost_metrics",
        lambda hours, limit, task: {
            "window_hours": hours,
            "manifest_costs": [
                {"density": "core", "task": None, "tokens_approx": 10},
                {"density": "task", "task": task, "tokens_approx": 20},
                {"density": "full", "task": None, "tokens_approx": 40},
            ],
            "request_hotspots": [],
            "tool_output_hotspots": [],
        },
    )

    result = runner.invoke(app, ["cost", "--hours", "2", "--limit", "3", "--task", "backend"])

    assert result.exit_code == 0
    assert "TOOLS_COST[2h]:manifest_core~10t task(backend)~20t full~40t" in result.output
