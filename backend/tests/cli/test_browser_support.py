from __future__ import annotations

from cli.lib.browser_support import parse_agent_console


def test_parse_agent_console_collects_initial_errors_and_multiline_warnings() -> None:
    errors, warnings = parse_agent_console(
        """[error] Uncaught Error: broken
[warning] The chart has invalid dimensions,
       add a minWidth to the container.
[log] ignored
"""
    )

    assert errors == ["[error] Uncaught Error: broken"]
    assert warnings == [
        "[warning] The chart has invalid dimensions,\nadd a minWidth to the container."
    ]


def test_parse_agent_console_ignores_daemon_noise() -> None:
    errors, warnings = parse_agent_console(
        "⚠ --profile ignored: daemon already running\nregular output"
    )

    assert errors == []
    assert warnings == []


def test_default_vm_host_reuses_cached_address_while_cdp_answers(tmp_path, monkeypatch) -> None:
    from cli.lib import browser_support as support

    lookups: list[str] = []
    monkeypatch.setattr(support, "_lookup_browser_vm_host", lambda _values, vmid: lookups.append(vmid) or "192.0.2.10")
    reachable = {"192.0.2.10": True}
    monkeypatch.setattr(support, "cdp_reachable", lambda host, **_kwargs: reachable.get(host, False))
    values = {"XDG_RUNTIME_DIR": str(tmp_path)}
    assert support.default_browser_vm_host(values) == "192.0.2.10"
    assert support.default_browser_vm_host(values) == "192.0.2.10"
    assert lookups == ["100"]
    reachable["192.0.2.10"] = False  # Stale cache: re-resolve through the guest agent.
    assert support.default_browser_vm_host(values) == "192.0.2.10"
    assert lookups == ["100", "100"]


def test_vm_session_port_reuses_cache_and_starts_only_when_asked(tmp_path, monkeypatch) -> None:
    from cli.lib import browser_support as support

    calls: list[tuple[str, ...]] = []
    running: dict[int, bool] = {}

    def vm(host, *args, values, timeout):
        calls.append(args)
        if args[0] == "ensure":
            running[9305] = True
            return [{"key": args[1], "port": 9305}]
        return [{"key": support.vm_session_key("research"), "port": 9305, "state": "active" if running else "inactive"}]

    monkeypatch.setattr(support, "_vm_session", vm)
    monkeypatch.setattr(support, "cdp_reachable", lambda host, *, port=9222, timeout=2.0: running.get(port, False))
    values = {"XDG_RUNTIME_DIR": str(tmp_path)}
    assert support.vm_session_port("192.0.2.10", "research", values, start=False) is None
    assert support.vm_session_port("192.0.2.10", "research", values) == 9305
    assert support.vm_session_port("192.0.2.10", "research", values) == 9305
    assert [call[0] for call in calls] == ["status", "ensure"]
    assert support.vm_session_key("research") != support.vm_session_key("research-b")
