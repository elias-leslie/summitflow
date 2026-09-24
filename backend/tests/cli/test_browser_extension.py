from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

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


def test_inventory_uses_structured_owner_contract_without_browser_lock(tmp_path, monkeypatch) -> None:
    requests: list[dict[str, Any]] = []

    def dispatch(_record, argv, *, context):
        requests.append(json.loads(argv[1]))
        assert context == _context(tmp_path)
        return 0

    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr(browser, "_local_ai_command_lock", lambda: pytest.fail("inventory must not acquire the browser lock"))
    monkeypatch.setattr("cli.extensions.dispatch_extension", dispatch)
    assert browser.run_registered(object(), ["inventory", "--json"], _context(tmp_path)) == 0
    assert requests[0]["operation"] == "inventory"
    assert requests[0]["command"] == "inventory"
    assert requests[0]["args"] == []
    assert requests[0]["endpoint"] is None
    assert requests[0]["launch"]["prefix"][:4] == ["--profile", "AI", "--executable-path", "/usr/bin/chrome"]


def test_local_checks_have_independent_sessions_and_locks(tmp_path, monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    requests = []
    entered = Barrier(2)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp")
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")

    def dispatch(_record, argv, *, context):
        requests.append(json.loads(argv[1]))
        entered.wait(timeout=3)
        return 0

    monkeypatch.setattr("cli.extensions.dispatch_extension", dispatch)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: browser.run_registered(object(), ["check", "https://example.test"], _context(tmp_path)), range(2)))
    assert results == [0, 0]
    assert len({r["check"]["session"] for r in requests}) == 2
    assert len({r["check"]["screenshot_path"] for r in requests}) == 2
    assert len({r["launch"]["isolation_root"] for r in requests}) == 2


def test_explicit_shared_check_still_uses_global_lock(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp")
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with browser._local_ai_command_lock() as acquired:
        assert acquired
        assert browser.run_registered(object(), ["check", "--session", "st-local-ai", "https://example.test"], _context(tmp_path)) == 75


def test_named_check_mutex_releases_without_files_and_protects_same_session(tmp_path, monkeypatch) -> None:
    from cli.lib import browser_policy

    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp")
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr(browser_policy, "system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    launch = browser_policy.isolated_check_launch("same-session", agent_browser_bin="/bin/agent-browser")
    with browser._local_ai_command_lock(isolation_root=str(launch["isolation_root"])) as acquired:
        assert acquired
        assert browser.run_registered(object(), ["check", "--session", "same-session", "https://example.test"], _context(tmp_path)) == 75
    with browser._local_ai_command_lock(isolation_root=str(launch["isolation_root"])) as acquired:
        assert acquired
    assert not Path(str(launch["isolation_root"])).with_suffix(".lock").exists()


def test_default_check_ignores_shared_profile_and_session_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp")
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_SESSION", "custom-shared")
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_PROFILE", "/tmp/shared-profile")
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_VISIBLE", "1")
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    request, _ = browser._build_request(["check", "https://example.test"], _context(tmp_path))
    check = cast(dict[str, Any], request["check"])
    launch = cast(dict[str, Any], request["launch"])
    assert check["session"] != "custom-shared"
    assert launch["window_mode"] == "headless"
    assert "/tmp/shared-profile" not in launch["prefix"]


def test_isolated_reaper_routes_without_chrome_or_project_resolution(tmp_path, monkeypatch):
    requests = []
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/managed/agent-browser")
    monkeypatch.setattr(browser, "current_root", lambda: tmp_path)
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda *a: pytest.fail("cleanup must not prepare a Chrome launch"))
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda record, argv, **kw: requests.append(json.loads(argv[1])) or 0)
    assert browser.run_registered(object(), ["reap-isolated", "--dry-run"], {}) == 0
    assert requests[0]["operation"] == "reap-isolated"
    assert requests[0]["args"] == ["--dry-run"]
    assert requests[0]["launch"]["prefix"] == []
    assert requests[0]["launch"]["window_mode"] == "none"
