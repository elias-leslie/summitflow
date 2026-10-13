from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.commands import browser
from cli.lib import browser_agent_sessions as agent_sessions

NOW = 10_000_000_000


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for key in agent_sessions.IDENTITY_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("ST_BROWSER_TARGET", raising=False)
    monkeypatch.delenv(agent_sessions.SHARED_PROFILE_ENV, raising=False)


def _record():
    operations = {name: SimpleNamespace(request_contract_version=2) for name in
                  ("capabilities", "help", "observe", "run", "extract", "session", "workflow", "selected-tabs")}
    return SimpleNamespace(manifest=SimpleNamespace(structured_operations=operations))


def _context(tmp_path: Path) -> dict[str, object]:
    return {"contract_version": 1, "project_id": "fixture", "project_root": str(tmp_path), "cwd": str(tmp_path)}


@pytest.fixture
def vm_dispatch(monkeypatch, tmp_path):
    requests: list[dict] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr(browser, "_proxmox_reachable", lambda: True)
    monkeypatch.setattr(browser, "_managed_vm_endpoint", lambda name: {
        "host": "192.0.2.10", "port": 9301, "ws": "ws://192.0.2.10:9301/s", "source": "proxmox-session", "debug_local": False})
    monkeypatch.setattr(browser, "_endpoint_payload", lambda engine, live: {
        "host": "192.0.2.10", "port": 9222, "ws": "ws://192.0.2.10:9222", "source": "fixture", "debug_local": False})
    monkeypatch.setattr("cli.extensions.dispatch_extension",
                        lambda _record, argv, **_kw: requests.append(json.loads(argv[1])) or 0)
    return requests


def test_agent_identity_prefers_explicit_owner_then_native_session_ids(monkeypatch) -> None:
    assert agent_sessions.agent_identity() is None
    monkeypatch.setenv("ST_SESSION_ID", "aico-root-1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "2ea4d7ec-f066-4844-a6a0-b79a8b2b4ad5")
    assert agent_sessions.agent_identity() == "2ea4d7ec-f066-4844-a6a0-b79a8b2b4ad5"
    monkeypatch.setenv("ST_BROWSER_OWNER", "task-7")
    assert agent_sessions.agent_identity() == "task-7"


@pytest.mark.parametrize("argv", [["open", "https://example.com"], ["--proxmox", "snapshot"], ["observe"]])
def test_agent_plain_command_runs_in_its_own_managed_vm_session(tmp_path, monkeypatch, vm_dispatch, argv) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-a")
    monkeypatch.setenv("AICO_PROJECT_ID", "demo")
    ensured: list[tuple[str, str]] = []
    monkeypatch.setattr(agent_sessions, "ensure_session", lambda name, owner: ensured.append((name, owner)))
    assert browser.run_registered(_record(), argv, _context(tmp_path)) == 0
    name = agent_sessions.default_session_name("thread-a")
    assert name.startswith("demo-") and ensured == [(name, "thread-a")]
    request = vm_dispatch[0]
    assert (request["target"], request["launch"]["managed_session"]) == ("proxmox", name)
    assert request["endpoint"]["port"] == 9301


def test_paused_agent_session_fails_clearly_without_switching(tmp_path, monkeypatch, vm_dispatch, capsys) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-a")
    monkeypatch.setattr(agent_sessions, "session_state", lambda name, actor: "paused")
    assert browser.run_registered(_record(), ["snapshot"], _context(tmp_path)) == 75
    assert not vm_dispatch
    assert "BROWSER_SESSION_PAUSED" in capsys.readouterr().err


def test_agent_session_never_falls_back_to_local_chrome(tmp_path, monkeypatch, vm_dispatch, capsys) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-a")
    monkeypatch.setattr(agent_sessions, "ensure_session", lambda name, owner: None)
    monkeypatch.setattr(browser, "_proxmox_reachable", lambda: False)
    with pytest.raises(browser.typer.Exit) as exc:
        browser.run_registered(_record(), ["snapshot"], _context(tmp_path))
    assert exc.value.exit_code == 69 and not vm_dispatch
    assert "BROWSER_VM_UNREACHABLE" in capsys.readouterr().err


def test_unmanaged_local_fallback_is_recorded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser, "_proxmox_reachable", lambda: False)
    assert browser._select_default_target("proxmox", False, "open", ["open", "https://example.com"]) == "local-ai"
    rows = (tmp_path / "state" / "st-browser" / "local-fallbacks.jsonl").read_text().splitlines()
    assert json.loads(rows[0])["reason"] == "vm-unreachable"


def test_shared_profile_is_held_by_one_live_agent_until_released() -> None:
    assert agent_sessions.claim_profile("jobs", "agent-a", owner_alive=lambda _a: True) is None
    conflict = agent_sessions.claim_profile("jobs", "agent-b", owner_alive=lambda _a: True)
    assert conflict and conflict.startswith("SHARED_PROFILE_HELD profile=jobs holder=agent-a")
    # An ended holder no longer blocks anyone.
    assert agent_sessions.claim_profile("jobs", "agent-b", owner_alive=lambda _a: False) is None
    assert not agent_sessions.release_profile("jobs", "agent-a")
    assert agent_sessions.release_profile("jobs", "agent-b")


def test_shared_profile_command_uses_the_profile_session_and_owner(tmp_path, monkeypatch, vm_dispatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-a")
    monkeypatch.setattr(agent_sessions, "agent_alive", lambda _a: True)
    ensured: list[tuple[str, str]] = []
    monkeypatch.setattr(agent_sessions, "ensure_session", lambda name, owner: ensured.append((name, owner)))
    assert browser.run_registered(_record(), ["--shared-profile", "jobs", "snapshot"], _context(tmp_path)) == 0
    assert ensured == [("jobs", "profile:jobs")]
    assert vm_dispatch[0]["launch"]["managed_session"] == "jobs"
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-b")
    assert browser.run_registered(_record(), ["--shared-profile", "jobs", "snapshot"], _context(tmp_path)) == 75
    assert len(vm_dispatch) == 1


def _session(**overrides):
    return {"name": "s", "actor": "a", "state": "active", "paused": False, "runtime_state": "running",
            "last_used_ms": NOW, **overrides}


@pytest.mark.parametrize(("session", "alive", "expected"), [
    (_session(), True, None),
    (_session(last_used_ms=NOW - agent_sessions.IDLE_CLOSE_MS), True, "idle"),
    (_session(last_used_ms=NOW - agent_sessions.DEAD_OWNER_GRACE_MS), False, "owner ended"),
    (_session(last_used_ms=NOW - 1000), False, None),
    (_session(paused=True, last_used_ms=NOW - agent_sessions.IDLE_CLOSE_MS * 3), False, None),
    (_session(paused=True, last_used_ms=NOW - agent_sessions.PAUSE_CLOSE_MS), True, "paused too long"),
    (_session(runtime_state="dormant", last_used_ms=0), False, None),
])
def test_reap_decision(session, alive, expected) -> None:
    assert agent_sessions.reap_decision(session, NOW, alive=lambda _a: alive, paused_since=lambda _n: None) == expected


def test_reap_closes_unused_sessions_and_stops_vm_orphans() -> None:
    closed: list[str] = []
    kept: list[set[str]] = []
    result = agent_sessions.reap(
        now_ms=NOW,
        inventory=lambda: [_session(name="busy"), _session(name="gone", last_used_ms=0)],
        alive=lambda _a: True, close=lambda name, actor: closed.append(name) or True,
        vm_orphans=lambda keep: kept.append(keep) or ["orphan"])
    assert closed == ["gone"] and result["vm_orphans_stopped"] == ["orphan"]
    assert kept == [{browser.browser_support.vm_session_key("busy")}]


def test_reclaim_closes_least_recently_used_idle_vm_session_never_paused() -> None:
    vm = {"target": "proxmox"}
    inventory = [
        _session(name="newer", last_used_ms=NOW - 120_000, runtime=vm),
        _session(name="oldest-paused", paused=True, last_used_ms=0, runtime=vm),
        _session(name="older", last_used_ms=NOW - 600_000, runtime=vm),
        _session(name="just-used", last_used_ms=NOW, runtime=vm),
    ]
    closed: list[str] = []
    assert agent_sessions.reclaim_one("me", now_ms=NOW, inventory=lambda: inventory,
                                      close=lambda name, _a: closed.append(name) or True) == "older"
    assert closed == ["older"]


def test_wait_for_resume_outcomes() -> None:
    states = iter(["paused", "paused", "active"])
    assert agent_sessions.wait_for_resume("s", "a", 60, poll_s=0, state=lambda *_: next(states)) == 0
    assert agent_sessions.wait_for_resume("s", "a", 60, poll_s=0, state=lambda *_: "closed") == 3
    assert agent_sessions.wait_for_resume("s", "a", 0, poll_s=0, state=lambda *_: "paused") == 124


def test_pause_reason_is_recorded_pushed_and_cleared_on_resume(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-a")
    pushed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(agent_sessions, "notify_owner", lambda *args: pushed.append(args) or True)
    monkeypatch.setattr(browser, "_run_registered", lambda _record, argv, _context: 0)
    name = agent_sessions.default_session_name("thread-a")
    assert browser.run_registered(_record(), ["session", "pause", "--reason", "login needed: example.com"], _context(tmp_path)) == 0
    assert agent_sessions.pause_reason(name) == "login needed: example.com"
    assert pushed == [(name, "thread-a", "login needed: example.com")]
    assert agent_sessions.runtime_link(name, "thread-a").endswith(f"?browser={name}&actor=thread-a")
    assert browser.run_registered(_record(), ["session", "resume"], _context(tmp_path)) == 0
    assert agent_sessions.pause_reason(name) is None
