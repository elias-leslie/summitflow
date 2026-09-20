from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
import typer

from app.services.browser_targets import BrowserTargetError
from cli.commands import browser


def _context(tmp_path: Path) -> dict[str, object]:
    return {
        "contract_version": 1,
        "project_id": "fixture",
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
        "api_base": "http://localhost:8001/api",
        "agent_hub_url": "http://localhost:8003",
        "output": {"human": False, "compact": True, "progress_only": False},
    }


def _forbid_dispatch(*args, **kwargs):
    pytest.fail("blocked browser request reached the owner dispatcher")


def test_proxmox_loopback_navigation_is_blocked_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(object(), ["--proxmox", "open", "http://127.0.0.1:3000"], _context(tmp_path))
    assert exc.value.exit_code == 2


def test_unapproved_local_session_is_blocked_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(object(), ["--session", "parallel", "snapshot"], _context(tmp_path))
    assert exc.value.exit_code == 75


def test_unsafe_remote_endpoint_is_blocked_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr(browser, "_resolve_endpoint", lambda engine=None: (_ for _ in ()).throw(BrowserTargetError("unsafe")))
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(object(), ["--proxmox", "health"], _context(tmp_path))
    assert exc.value.exit_code == 1


def test_busy_local_target_never_dispatches(tmp_path, monkeypatch) -> None:
    @contextmanager
    def busy():
        yield False

    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr(browser, "_local_ai_command_lock", busy)
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    assert browser.run_registered(object(), ["snapshot"], _context(tmp_path)) == 75


def test_allowed_local_request_is_normalized_and_dispatched_inside_policy(tmp_path, monkeypatch, capsys) -> None:
    observed: list[tuple[list[str], dict[str, object]]] = []

    @contextmanager
    def available():
        yield True

    def dispatch(record, argv, *, context):
        observed.append((argv, context))
        return 7

    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr(browser, "_local_ai_command_lock", available)
    monkeypatch.setattr("cli.extensions.dispatch_extension", dispatch)
    assert browser.run_registered(object(), ["open", "https://example.test"], _context(tmp_path)) == 7
    assert observed[0][0][0] == "--request"
    request = json.loads(observed[0][0][1])
    assert request["target"] == "local-ai"
    assert request["args"] == ["--session", "st-local-ai", "open", "https://example.test"]
    assert request["launch"]["agent_browser_bin"] == "/bin/agent-browser"
    assert request["launch"]["prefix"][:4] == ["--profile", "AI", "--executable-path", "/usr/bin/chrome"]
    assert observed[0][1] == _context(tmp_path)
    assert "example.test" not in capsys.readouterr().out
