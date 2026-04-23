"""Tests for st tools CLI auth and routing."""

from __future__ import annotations

from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from cli.commands.tools import _api_request, _build_internal_headers, app

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
    assert "st service" in result.output
    assert "sf-browser" in result.output


def test_tools_catalog_json_includes_registry_source() -> None:
    result = runner.invoke(app, ["catalog"], obj=None)

    assert result.exit_code == 0
    assert "tool-registry.json" in result.output
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
