"""Tests for project-aware browser route resolution."""

from __future__ import annotations

import pytest

from app.services import browser_routes
from app.services.browser_routes import (
    BrowserRouteError,
    resolve_browser_location,
    resolve_browser_project_route,
)


def test_browser_route_prefers_browser_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        browser_routes,
        "get_project_identity",
        lambda _project: {"hosts": {"browser_frontend": "terminal.summitflow.dev", "production_frontend": "old.example"}},
    )
    monkeypatch.setattr(browser_routes, "get_project_canonical_id", lambda *_args, **_kwargs: "a-term")

    route = resolve_browser_project_route("terminal")

    assert route.project_id == "a-term"
    assert route.url == "https://terminal.summitflow.dev/"
    assert route.source == "hosts.browser_frontend"


def test_browser_route_falls_back_to_production_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        browser_routes,
        "get_project_identity",
        lambda _project: {"hosts": {"production_frontend": "dev.summitflow.dev"}},
    )
    monkeypatch.setattr(browser_routes, "get_project_canonical_id", lambda *_args, **_kwargs: "summitflow")

    route = resolve_browser_project_route("summitflow")

    assert route.url == "https://dev.summitflow.dev/"
    assert route.source == "hosts.production_frontend"


def test_browser_location_passes_url_through() -> None:
    assert resolve_browser_location("https://example.com/path") == "https://example.com/path"
    assert resolve_browser_location("data:text/html,ok") == "data:text/html,ok"


def test_browser_route_requires_browser_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_routes, "get_project_identity", lambda _project: {"hosts": {}})
    monkeypatch.setattr(browser_routes, "get_project_canonical_id", lambda *_args, **_kwargs: "empty")

    with pytest.raises(BrowserRouteError, match="no browser_frontend"):
        resolve_browser_project_route("empty")
