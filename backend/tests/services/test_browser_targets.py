"""Tests for browser target safety policy."""

from __future__ import annotations

import pytest

from app.services.browser_targets import BrowserTargetError, resolve_browser_endpoint


def test_browser_endpoint_requires_configured_host() -> None:
    with pytest.raises(BrowserTargetError, match="not configured"):
        resolve_browser_endpoint(env={})


def test_browser_endpoint_rejects_localhost_by_default() -> None:
    with pytest.raises(BrowserTargetError, match="server-local"):
        resolve_browser_endpoint(env={"SF_BROWSER_HOST": "127.0.0.1"})


def test_browser_endpoint_allows_localhost_with_debug_override() -> None:
    endpoint = resolve_browser_endpoint(
        env={"SF_BROWSER_HOST": "127.0.0.1", "SF_BROWSER_ALLOW_LOCAL": "1"}
    )

    assert endpoint.host == "127.0.0.1"
    assert endpoint.port == 9222
    assert endpoint.debug_local is True


def test_browser_endpoint_uses_default_host_when_explicit_host_missing() -> None:
    endpoint = resolve_browser_endpoint(env={"SF_BROWSER_DEFAULT_HOST": "192.0.2.88"})

    assert endpoint.host == "192.0.2.88"
    assert endpoint.source == "SF_BROWSER_DEFAULT_HOST"


def test_browser_endpoint_uses_live_host_and_port() -> None:
    endpoint = resolve_browser_endpoint(
        live=True,
        env={
            "SUMMITFLOW_LIVE_BROWSER_HOST": "192.0.2.44",
            "SUMMITFLOW_LIVE_BROWSER_PORT": "9333",
            "SF_BROWSER_HOST": "192.0.2.55",
        },
    )

    assert endpoint.host == "192.0.2.44"
    assert endpoint.port == 9333
    assert endpoint.source == "SUMMITFLOW_LIVE_BROWSER_HOST"


def test_browser_endpoint_uses_lightpanda_default_port() -> None:
    endpoint = resolve_browser_endpoint(env={"SF_BROWSER_HOST": "192.0.2.44"}, engine="lightpanda")

    assert endpoint.port == 9223
