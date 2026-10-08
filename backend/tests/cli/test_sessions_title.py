"""Exact title forwarding stays generation-fenced and content-free."""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from cli.lib import root_title
from cli.main import app

DESCRIPTOR = {"owner": "aico", "requestId": "root-fixture", "hostIdentity": "deadbeef",
              "logicalSessionId": "logical-fixture", "surfaceLocator": "aico://deadbeef",
              "generation": "a" * 64, "status": "running"}


def install_owner(monkeypatch, handler):
    monkeypatch.setattr(root_title, "_owner_client", lambda _: httpx.Client(
        base_url="http://fixture", transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("surface", ["aico", "a-term"])
def test_title_fences_exact_owner_generation_without_fleet_or_content_output(monkeypatch, surface):
    requests = []
    descriptor = {**DESCRIPTOR, "owner": surface}
    label = "Project · Focus 🐾"

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={**descriptor, "label": label, "unexpected": "private-owner-content"})

    install_owner(monkeypatch, handle)
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", f"  {label}  ", "--surface", surface])
    assert result.exit_code == 0, result.output
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", "/v1/roots/root-fixture"), ("POST", "/v1/roots/root-fixture/title")]
    assert json.loads(requests[1].content) == {"generation": "a" * 64, "label": label}
    assert json.loads(result.output) == {"root": "root-fixture", "owner": surface,
        "generation": "a" * 64, "status": "running", "applied": True}
    assert label not in result.output and "private-owner-content" not in result.output


@pytest.mark.parametrize("label", ["", " ", "\ufeff", "\ufeff \ufeff", "x" * 161,
    "é" * 80 + "x", "🐾" * 40 + "x", "🐾" * 41, "\ud800",
    "Focus\nNext", "Focus\rNext", "Focus\tNext", "Focus\x1b[31m", "Focus\x00",
    "Focus\x7f", "Focus\u2028Next", "Focus\u2029Next"])
def test_invalid_labels_never_reach_owner_or_echo_input(monkeypatch, label):
    monkeypatch.setattr(root_title, "_owner_client", lambda _: pytest.fail("Invalid label reached owner"))
    with pytest.raises(ValueError):
        root_title.title_root("root-fixture", label)
    if label.strip() and "\ud800" not in label:
        result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", label])
        assert result.exit_code == 1
        assert label not in result.output


@pytest.mark.parametrize("change", [
    {"owner": "a-term"}, {"requestId": "other"}, {"generation": "invalid"},
    {"status": "ended"}, {"status": "uncertain"}, {"generation": None}, {"hostIdentity": None},
])
def test_mismatched_or_unavailable_descriptor_never_mutates(monkeypatch, change):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={**DESCRIPTOR, **change})

    install_owner(monkeypatch, handle)
    with pytest.raises(ValueError, match="Exact running owner root unavailable"):
        root_title.title_root("root-fixture", "Focus")
    assert [r.method for r in requests] == ["GET"]


@pytest.mark.parametrize("status", [401, 403, 404, 409, 410, 503])
def test_owner_failure_content_is_never_echoed_or_retried(monkeypatch, status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=DESCRIPTOR) if request.method == "GET" else httpx.Response(status, json={"label": "secret-fixture"})

    install_owner(monkeypatch, handle)
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", "secret-fixture"])
    assert result.exit_code == 1 and "secret-fixture" not in result.output
    assert len(requests) == 2


def test_acknowledgment_changed_identity_and_response_limit_fail_closed(monkeypatch):
    install_owner(monkeypatch, lambda request: httpx.Response(200, json={
        **DESCRIPTOR, **({"generation": "b" * 64} if request.method == "POST" else {})}))
    with pytest.raises(ValueError, match="unconfirmed"):
        root_title.title_root("root-fixture", "Focus")
    install_owner(monkeypatch, lambda _: httpx.Response(200, content=b"x" * (16 * 1024 + 1)))
    with pytest.raises(ValueError, match="acknowledgment unavailable"):
        root_title.title_root("root-fixture", "Focus")


@pytest.mark.parametrize("base", ["https://127.0.0.1:8002", "http://remote.invalid:8002", "http://user:password@localhost:8002",
    "http://localhost:8002/path", "http://localhost:8002?token=secret", "http://localhost:invalid"])
def test_aterm_configuration_preserves_local_owner_boundary(monkeypatch, base):
    monkeypatch.setenv("A_TERM_ROOT_CONTROL_URL", base)
    with pytest.raises(ValueError, match="loopback"):
        root_title._owner_client("a-term")


def test_help_advertises_exact_surface_and_byte_bound():
    result = CliRunner().invoke(app, ["sessions", "title", "--help"])
    assert result.exit_code == 0
    assert "160 UTF-8 bytes" in result.output
    assert "aico" in result.output and "a-term" in result.output


@pytest.mark.parametrize("label,expected", [("\nFocus\r", "Focus"), ("Project\u00a0Focus", "Project\u00a0Focus"),
    ("Focus\u202eNext", "Focus\u202eNext"), ("Focus\ufeffNext", "Focus\ufeffNext"),
    ("e\u0301", "e\u0301"), ("x" * 160, "x" * 160), ("é" * 80, "é" * 80), ("🐾" * 40, "🐾" * 40)])
def test_label_unicode_contract_matches_owners(label, expected):
    assert root_title._label(label) == expected


@pytest.mark.parametrize("codepoint", [*range(0x0009, 0x000E), 0x0020, 0x00A0, 0x1680,
    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF],
    ids=lambda codepoint: f"U+{codepoint:04X}")
def test_label_trims_every_ecmascript_trim_character(codepoint):
    char = chr(codepoint)
    assert root_title._label(f"{char}Focus{char}") == "Focus"


@pytest.mark.parametrize("codepoint", [*range(0x001C, 0x0020), 0x0085],
    ids=lambda codepoint: f"U+{codepoint:04X}")
@pytest.mark.parametrize("position", ["leading", "trailing", "interior"])
def test_python_only_trim_controls_never_reach_owner(monkeypatch, codepoint, position):
    char = chr(codepoint)
    label = {"leading": f"{char}Focus", "trailing": f"Focus{char}", "interior": f"Focus{char}Next"}[position]
    monkeypatch.setattr(root_title, "_owner_client", lambda _: pytest.fail("Invalid label reached owner"))
    with pytest.raises(ValueError, match="control-free"):
        root_title.title_root("root-fixture", label)


def test_local_owner_timeout_never_echoes_transport_details_or_retries(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ConnectError("private-owner-content", request=request)

    install_owner(monkeypatch, handle)
    result = CliRunner().invoke(app, ["sessions", "title", "root-fixture", "private-label-content"])
    assert result.exit_code == 1
    assert "unconfirmed" in result.output
    assert "private-owner-content" not in result.output and "private-label-content" not in result.output
    assert len(requests) == 1


def test_aico_uses_existing_runtime_and_socket_override(monkeypatch):
    sockets = []
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/fixture/runtime")
    monkeypatch.delenv("AICO_GUI_CONTROL_SOCKET", raising=False)
    monkeypatch.setattr(httpx, "HTTPTransport", lambda *, uds: (
        sockets.append(uds) or httpx.MockTransport(lambda _: httpx.Response(200))))
    with root_title._owner_client("aico"):
        pass
    monkeypatch.setenv("AICO_GUI_CONTROL_SOCKET", "/fixture/explicit.sock")
    with root_title._owner_client("aico"):
        pass
    assert sockets == ["/fixture/runtime/aico/gui-control.sock", "/fixture/explicit.sock"]
