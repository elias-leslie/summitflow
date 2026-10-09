"""`st sessions title` is a compatibility alias of the owner's `st aico root title`."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.main import app


@pytest.mark.parametrize("arguments,surface", [
    (["root-fixture", "  Project · Focus 🐾  "], "aico"),
    (["root-fixture", "Focus · Next", "--surface", "a-term"], "a-term"),
])
def test_alias_forwards_exact_argv_to_owner_root_title(monkeypatch, arguments, surface):
    observed = []

    def dispatch(record, argv, **kwargs):
        observed.append((record.binding.namespace, argv))
        return 0

    monkeypatch.setattr("cli.extensions.extension_context", lambda *_: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", dispatch)
    result = CliRunner().invoke(app, ["sessions", "title", *arguments])
    assert result.exit_code == 0, result.output
    assert observed == [("aico", ["root", "title", "--surface", surface, "--", arguments[0], arguments[1]])]
    assert result.output == ""


@pytest.mark.parametrize("code", [1, 2])
def test_alias_propagates_owner_failure_without_echoing_label(monkeypatch, code):
    monkeypatch.setattr("cli.extensions.extension_context", lambda *_: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *args, **kwargs: code)
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", "secret-fixture"])
    assert result.exit_code == code
    assert "secret-fixture" not in result.output


def test_alias_rejects_unknown_surface_before_dispatch(monkeypatch):
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *args, **kwargs: pytest.fail("dispatched"))
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", "Focus", "--surface", "remote"])
    assert result.exit_code == 2


def test_help_advertises_alias_surface_and_byte_bound():
    result = CliRunner().invoke(app, ["sessions", "title", "--help"])
    assert result.exit_code == 0
    assert "160 UTF-8 bytes" in result.output
    assert "aico" in result.output and "a-term" in result.output
    assert "st aico root title" in result.output
