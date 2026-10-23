"""`st sessions title` is a compatibility alias of the owner's `st aico root title`."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.main import app


@pytest.fixture(autouse=True)
def _no_live_tether(monkeypatch):
    """Pre-cutover baseline: Tether is not running, whatever runs on this host."""
    monkeypatch.setattr("app.services.tether.available", lambda *_: False)
    monkeypatch.delenv("AICO_GUI_CONTROL_SOCKET", raising=False)


@pytest.mark.parametrize("arguments", [
    ["root-fixture", "  Project · Focus 🐾  "],
    ["root-fixture", "Focus · Next", "--surface", "aico"],
])
def test_alias_forwards_exact_argv_to_owner_root_title(monkeypatch, arguments):
    observed = []

    def dispatch(record, argv, **kwargs):
        observed.append((record.binding.namespace, argv))
        return 0

    monkeypatch.setattr("cli.extensions.extension_context", lambda *_: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", dispatch)
    result = CliRunner().invoke(app, ["sessions", "title", *arguments])
    assert result.exit_code == 0, result.output
    assert observed == [("aico", ["root", "title", "--", arguments[0], arguments[1]])]
    assert result.output == ""


@pytest.mark.parametrize("code", [1, 2])
def test_alias_propagates_owner_failure_without_echoing_label(monkeypatch, code):
    monkeypatch.setattr("cli.extensions.extension_context", lambda *_: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *args, **kwargs: code)
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", "secret-fixture"])
    assert result.exit_code == code
    assert "secret-fixture" not in result.output


@pytest.mark.parametrize("surface", ["remote", "a-term"])
def test_alias_rejects_unknown_surface_before_dispatch(monkeypatch, surface):
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *args, **kwargs: pytest.fail("dispatched"))
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", "Focus", "--surface", surface])
    assert result.exit_code == 2


def test_help_advertises_alias_surface_and_byte_bound():
    result = CliRunner().invoke(app, ["sessions", "title", "--help"])
    assert result.exit_code == 0
    assert "160 UTF-8 bytes" in result.output
    assert "aico" in result.output and "a-term" not in result.output
    assert "st aico root title" in result.output


@pytest.mark.parametrize("surface,available,route", [
    ("aico", True, ["--root-socket", "/fixture/tether.sock"]),
    ("tether", False, ["--root-socket", "/fixture/tether.sock"]),
    ("aico", False, []),
])
def test_alias_routes_aico_roots_through_running_tether(monkeypatch, surface, available, route):
    observed = []
    monkeypatch.setenv("TETHER_SOCKET", "/fixture/tether.sock")
    monkeypatch.setattr("app.services.tether.available", lambda *_: available)
    monkeypatch.setattr("cli.extensions.extension_context", lambda *_: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda record, argv, **_: observed.append(argv) or 0)
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", "Focus", "--surface", surface])
    assert result.exit_code == 0, result.output
    assert observed == [["root", "title", *route, "--", "root-fixture", "Focus"]]
