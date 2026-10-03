from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
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


def test_old_owner_cannot_receive_a_managed_local_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    assert browser.run_registered(object(), ["--session", "parallel", "snapshot"], _context(tmp_path)) == 2


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


def test_registered_browser_help_and_manifest_describe_isolated_checks():
    from typer.testing import CliRunner

    from cli.extensions import register_extensions
    from cli.lib.usage import collect_usage_specs

    app = typer.Typer()

    @app.callback()
    def root():
        pass

    register_extensions(app)
    result = CliRunner().invoke(app, ["browser", "--help"])
    assert result.exit_code == 0
    assert "Checks use a fresh isolated headless profile by default" in result.output
    assert "check --session st-local-ai" in result.output
    assert "reap-isolated" in result.output
    specs = [spec for spec in collect_usage_specs(app) if spec.surface == "st.browser"]
    assert len(specs) == 1
    assert "local checks use isolated headless sessions; interactive commands share the Chrome AI profile" in specs[0].precautions


def _v2_record(operations=("capabilities", "help", "observe", "run", "extract", "session", "workflow", "selected-tabs")):
    return SimpleNamespace(manifest=SimpleNamespace(structured_operations={
        name: SimpleNamespace(request_contract_version=2, response_schema_version=1) for name in operations
    }))


@pytest.fixture
def structured_dispatch(tmp_path, monkeypatch):
    requests = []
    state = {"locked": False}

    @contextmanager
    def available():
        assert not state["locked"]
        state["locked"] = True
        try:
            yield True
        finally:
            state["locked"] = False

    def dispatch(_record, argv, *, context):
        request = json.loads(argv[1])
        assert state["locked"] == (request["target"] == "local-ai" and request["operation"] in {"observe", "run", "extract"} and not request["launch"].get("managed_session"))
        assert context == _context(tmp_path)
        requests.append(request)
        return 7

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr(browser, "_local_ai_command_lock", available)
    monkeypatch.setattr(browser, "_endpoint_payload", lambda engine, live: {"host": "browser.test", "port": 9222, "ws": "ws://browser.test", "source": "fixture", "debug_local": False})
    monkeypatch.setattr("cli.extensions.dispatch_extension", dispatch)
    return requests


@pytest.mark.parametrize("argv,payload", [
    (["observe"], {"interactive": False, "compact": True, "delta": True, "full": False}),
    (["observe", "--selector", "main", "--interactive", "--full"], {"selector": "main", "interactive": True, "compact": False, "delta": False, "full": True}),
    (["step", "fill", "@e2", "Two words; $(literal)"], {"actions": [["fill", "@e2", "Two words; $(literal)"]]}),
])
def test_v2_operations_have_minimal_session_scoped_wire_and_hold_lock(tmp_path, structured_dispatch, argv, payload):
    assert browser.run_registered(_v2_record(), argv, _context(tmp_path)) == 7
    request = structured_dispatch[0]
    assert set(request) == {"contract_version", "operation", "target", "command", "args", "root", "endpoint", "launch", "check", "default_viewport", "reaper", "payload"}
    assert request["contract_version"] == 2
    assert request["args"] == ["--session", "st-local-ai"]
    assert request["command"] == request["operation"]
    assert request["payload"] == payload
    assert request["check"] is request["default_viewport"] is None


@pytest.mark.parametrize("argv,operation,payload", [
    (["capabilities"], "capabilities", {}),
    (["capabilities", "forms"], "capabilities", {"topic": "forms"}),
    (["fill", "--help"], "help", {"command": ["fill"]}),
    (["get", "text", "--help"], "help", {"command": ["get", "text"]}),
    (["session", "--help"], "help", {"command": ["session"]}),
    (["workflow", "--help"], "help", {"command": ["workflow"]}),
    (["workflow", "record-stop", "--help"], "help", {"command": ["workflow", "record-stop"]}),
    (["--proxmox", "snapshot", "--help"], "help", {"command": ["snapshot"]}),
    (["help", "get", "text"], "help", {"command": ["get", "text"]}),
])
def test_capabilities_and_focused_help_require_no_browser_launch(tmp_path, monkeypatch, structured_dispatch, argv, operation, payload):
    if operation == "capabilities":
        monkeypatch.setattr(browser, "_agent_browser_bin", lambda: pytest.fail("capabilities resolved browser executable"))
    monkeypatch.setattr(browser, "_endpoint_payload", lambda *a, **k: pytest.fail("discovery resolved live endpoint"))
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda *a, **k: pytest.fail("discovery resolved Chrome"))
    assert browser.run_registered(_v2_record(), argv, _context(tmp_path)) == 7
    request = structured_dispatch[0]
    assert request["operation"] == operation
    assert request["payload"] == payload
    assert request["args"] == []
    assert request["endpoint"] is None
    assert request["launch"]["window_mode"] == "none"
    if operation == "help":
        assert request["launch"]["agent_browser_bin"] == "/bin/agent-browser"


@pytest.mark.parametrize("version", [None, 1, 3])
@pytest.mark.parametrize("argv,operation", [(["observe"], "observe"), (["step", "snapshot"], "run"), (["fill", "--help"], "help")])
def test_v2_negotiation_fails_before_dispatch_or_browser_setup(tmp_path, monkeypatch, capsys, version, argv, operation):
    record = _v2_record(()) if version is None else _v2_record((operation,))
    if version is not None:
        record.manifest.structured_operations[operation].request_contract_version = version
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: pytest.fail("unsupported operation resolved browser executable"))
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    assert browser.run_registered(record, argv, _context(tmp_path)) == 2
    captured = capsys.readouterr()
    assert f"does not support {operation} request contract version 2" in captured.out + captured.err


def test_run_file_forwards_owner_schema_and_resolves_all_local_artifacts(tmp_path, structured_dispatch, monkeypatch):
    monkeypatch.setattr(browser, "resolve_browser_location", lambda location: "https://project.test" if location == "fixture" else location)
    payload = {
        "actions": [["open", "fixture"], ["screenshot", "action.png"]],
        "postconditions": [{"kind": "text", "value": "Saved", "timeout_ms": 500}],
        "observation": {"selector": "main", "screenshot": "observation.png"},
        "screenshot": "receipt.png", "binding": None,
    }
    path = tmp_path / "actions.json"
    path.write_text(json.dumps(payload))
    assert browser.run_registered(_v2_record(), ["run", "--file", str(path)], _context(tmp_path)) == 7
    delivered = structured_dispatch[0]["payload"]
    assert delivered["actions"] == [["open", "https://project.test"], ["screenshot", str(tmp_path / "action.png")]]
    assert delivered["postconditions"] == payload["postconditions"]
    assert delivered["screenshot"] == str(tmp_path / "receipt.png")
    assert delivered["observation"]["screenshot"] == str(tmp_path / "observation.png")


def test_extract_file_is_forwarded_without_shell_parsing(tmp_path, structured_dispatch):
    payload = {"fields": {"title": {"selector": "h1"}, "links": {"selector": "a", "attribute": "href", "multiple": True}}, "binding": None}
    path = tmp_path / "fields.json"
    path.write_text(json.dumps(payload))
    assert browser.run_registered(_v2_record(), ["extract", f"--file={path}"], _context(tmp_path)) == 7
    assert structured_dispatch[0]["payload"] == payload


@pytest.mark.parametrize("command", ["open", "goto", "navigate"])
@pytest.mark.parametrize("workflow", ["run", "step"])
def test_every_structured_navigation_is_guarded_before_dispatch(tmp_path, monkeypatch, command, workflow):
    monkeypatch.delenv("ST_BROWSER_CONFIRM_LOCAL_URL", raising=False)
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: pytest.fail("blocked action resolved browser executable"))
    actions = [["snapshot"], [command, "http://127.0.0.1:3000/private"]]
    path = tmp_path / "actions.json"
    path.write_text(json.dumps({"actions": actions}))
    argv = ["run", "--file", str(path)] if workflow == "run" else ["step", *actions[1]]
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["--proxmox", *argv], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("action", [
    ["open", "https://example.test", "--profile", "other"],
    ["snapshot", "--session=other"], ["close", "--all"], ["session", "other"],
    ["--cdp", "ws://other", "snapshot"], ["open", "https://example.test", "--proxmox"],
    ["quit", "--all"], ["exit", "--all=true"], ["snapshot", "--action-policy=other"],
    ["open", "https://example.test", "-p", "other"],
    ["snapshot", "--idle-timeout", "500"], ["snapshot", "--idle-timeout=500"],
])
@pytest.mark.parametrize("workflow", ["run", "step"])
def test_structured_actions_cannot_override_host_authority(tmp_path, monkeypatch, action, workflow):
    path = tmp_path / "actions.json"
    path.write_text(json.dumps({"actions": [action]}))
    argv = ["run", "--file", str(path)] if workflow == "run" else ["step", *action]
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), argv, _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("argv", [
    ["observe", "--session", "other"], ["--session=other", "step", "snapshot"],
])
def test_explicit_structured_managed_selection_bypasses_local_singleton_lock(tmp_path, monkeypatch, structured_dispatch, argv):
    monkeypatch.setattr(browser, "_local_ai_command_lock", lambda: pytest.fail("managed sessions must use owner locks"))
    assert browser.run_registered(_v2_record(), argv, _context(tmp_path)) == 7
    assert structured_dispatch[0]["launch"]["managed_session"] == "other"
    assert structured_dispatch[0]["args"] == ["--session", "other"]


def test_structured_remote_session_and_observation_screenshot(tmp_path, structured_dispatch):
    assert browser.run_registered(_v2_record(), ["--proxmox", "observe", "--session=operator", "--screenshot", "page.png"], _context(tmp_path)) == 7
    assert structured_dispatch[0]["args"] == ["--session", "operator"]
    assert structured_dispatch[0]["payload"]["screenshot"] == str(tmp_path / "page.png")


def test_structured_screenshot_flags_do_not_become_output_paths(tmp_path, structured_dispatch):
    assert browser.run_registered(_v2_record(), ["step", "screenshot", "--full"], _context(tmp_path)) == 7
    assert structured_dispatch[0]["payload"]["actions"] == [["screenshot", "--full"]]
    assert browser.run_registered(_v2_record(), ["step", "screenshot", "--full", "page.png"], _context(tmp_path)) == 7
    assert structured_dispatch[1]["payload"]["actions"] == [["screenshot", "--full", str(tmp_path / "page.png")]]
    assert browser.run_registered(_v2_record(), ["step", "screenshot", "--screenshot-quality", "80", "--screenshot-dir=shots", "page.png"], _context(tmp_path)) == 7
    assert structured_dispatch[2]["payload"]["actions"] == [["screenshot", "--screenshot-quality", "80", f"--screenshot-dir={tmp_path / 'shots'}", str(tmp_path / "page.png")]]


@pytest.mark.parametrize("action", [["screenshot", "--annotate", "--full"], ["snapshot", "--json"], ["find", "role", "button", "click", "--name", "Save"], ["snapshot", "--max-output=5000"]])
def test_structured_actions_preserve_output_and_semantic_command_options(tmp_path, structured_dispatch, action):
    assert browser.run_registered(_v2_record(), ["step", *action], _context(tmp_path)) == 7
    assert structured_dispatch[0]["payload"]["actions"] == [action]


def test_structured_busy_session_does_not_dispatch(tmp_path, monkeypatch, structured_dispatch):
    @contextmanager
    def busy():
        yield False

    monkeypatch.setattr(browser, "_local_ai_command_lock", busy)
    assert browser.run_registered(_v2_record(), ["step", "snapshot"], _context(tmp_path)) == 75
    assert not structured_dispatch


def test_run_rejects_binding_for_a_different_session(tmp_path, monkeypatch):
    path = tmp_path / "actions.json"
    path.write_text(json.dumps({"actions": [["snapshot"]], "binding": {"session": "other", "target_id": None, "document_id": "doc"}}))
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["run", "--file", str(path)], _context(tmp_path))
    assert exc.value.exit_code == 2


def test_run_missing_file_fails_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["run", "--file", str(tmp_path / "missing.json")], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("tail", [
    ["--unknown"], ["--selector"], ["--full=true"], ["--interactive", "--interactive"],
    ["--session"], ["--session", "one", "--session=two"], ["trailing"],
])
def test_observe_rejects_malformed_options(tmp_path, monkeypatch, tail):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["observe", *tail], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("contents", ['[]', '{broken', '{"actions":"snapshot"}', '{"actions":["snapshot"]}', '{"actions":[]}'])
def test_run_rejects_non_structured_or_unreadable_json(tmp_path, monkeypatch, contents):
    path = tmp_path / "actions.json"
    path.write_text(contents)
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["run", "--file", str(path)], _context(tmp_path))
    assert exc.value.exit_code == 2


def test_check_viewport_subset_preserves_canonical_order_and_environment_dimensions(tmp_path, monkeypatch):
    monkeypatch.setenv("ST_BROWSER_CHECK_RESPONSIVE", "0")
    monkeypatch.setenv("ST_BROWSER_CHECK_DESKTOP_WIDTH", "1920")
    args, payload = browser._check_payload("proxmox", ["https://example.test", "--viewports=mobile,desktop", "page.png", "--session=operator"])
    assert args == ["--session", "operator", "check", "https://example.test", "page.png"]
    viewports = cast(list[dict[str, object]], payload["viewports"])
    assert [(row["label"], row["width"], row["path"]) for row in viewports] == [("desktop", 1920, "page.png"), ("mobile", 390, "page-mobile.png")]


@pytest.mark.parametrize("tail", [
    ["--unknown"], ["page.png", "trailing"], ["--session"], ["--session="],
    ["--session", "one", "--session", "two"], ["--viewports"],
    ["--viewports="], ["--viewports", "desktop,desktop"], ["--viewports", "tablet"],
])
def test_check_rejects_unknown_trailing_and_malformed_arguments(tail):
    with pytest.raises(typer.Exit) as exc:
        browser._check_payload("proxmox", ["https://example.test", *tail])
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("tail,payload", [
    (["create", "research"], {"action": "create", "name": "research"}),
    (["list"], {"action": "list"}), (["status", "research"], {"action": "status", "name": "research"}),
    (["pause", "research"], {"action": "pause", "name": "research"}),
    (["resume", "research"], {"action": "resume", "name": "research"}),
    (["close", "research"], {"action": "close", "name": "research"}),
    (["maintenance"], {"action": "maintenance", "dry_run": True}),
    (["maintenance", "--idle-ms", "1000", "--apply"], {"action": "maintenance", "idle_ms": 1000, "dry_run": False}),
])
def test_session_lifecycle_dispatches_owner_request_without_host_lock(tmp_path, monkeypatch, structured_dispatch, tail, payload):
    monkeypatch.setattr(browser, "_local_ai_command_lock", lambda: pytest.fail("lifecycle must use owner locks"))
    assert browser.run_registered(_v2_record(), ["session", *tail], _context(tmp_path)) == 7
    request = structured_dispatch[0]
    assert request["contract_version"] == 2
    assert request["operation"] == request["command"] == "session"
    assert request["payload"] == payload
    assert request["args"] == []
    assert request["launch"]["managed_session"] is None
    assert request["launch"]["minimize"] is False
    assert "--profile" not in request["launch"]["prefix"]


@pytest.mark.parametrize("tail", [
    [], ["create"], ["list", "extra"], ["status", "one", "extra"], ["invalid"],
    ["maintenance", "--idle-ms"], ["maintenance", "--idle-ms=0"],
    ["maintenance", "--idle-ms=-1"], ["maintenance", "--idle-ms=1.5"],
    ["maintenance", "--apply=true"], ["maintenance", "--apply", "--apply"],
    ["maintenance", "--idle-ms", "10", "--idle-ms", "20"],
    ["maintenance", "--unknown"], ["pause", "--session=one"],
])
def test_session_lifecycle_rejects_malformed_syntax(tmp_path, monkeypatch, tail):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["session", *tail], _context(tmp_path))
    assert exc.value.exit_code == 2


def test_session_lifecycle_rejects_remote_target(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["--proxmox", "session", "create", "research"], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("argv", [["--session", "research", "snapshot"], ["snapshot", "--session=research"]])
def test_managed_core_request_preserves_v1_envelope_and_delegates_session_lock(tmp_path, monkeypatch, structured_dispatch, argv):
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_PROFILE", "/tmp/shared-profile")
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_MINIMIZED", "1")
    monkeypatch.setenv("AGENT_BROWSER_PROFILE", "/tmp/another-shared-profile")
    monkeypatch.setattr(browser, "_local_ai_command_lock", lambda: pytest.fail("managed core request acquired global lock"))
    assert browser.run_registered(_v2_record(), argv, _context(tmp_path)) == 7
    request = structured_dispatch[0]
    assert request["contract_version"] == 1
    assert "payload" not in request
    assert request["operation"] == "agent"
    assert request["args"] == ["--session", "research", "snapshot"]
    assert request["launch"]["managed_session"] == "research"
    assert request["launch"]["prefix"][:2] == ["--executable-path", "/usr/bin/chrome"]
    assert "--profile" not in request["launch"]["prefix"]
    assert request["launch"]["minimize"] is False


def test_managed_names_do_not_serialize_independent_host_dispatches(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    entered = Barrier(2)
    requests = []
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr(browser, "_local_ai_command_lock", lambda: pytest.fail("independent managed sessions were globally locked"))

    def dispatch(_record, argv, *, context):
        requests.append(json.loads(argv[1]))
        entered.wait(timeout=3)
        return 0

    monkeypatch.setattr("cli.extensions.dispatch_extension", dispatch)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda name: browser.run_registered(_v2_record(), ["--session", name, "snapshot"], _context(tmp_path)), ["agent-a", "agent-b"]))
    assert results == [0, 0]
    assert {request["launch"]["managed_session"] for request in requests} == {"agent-a", "agent-b"}


def test_actor_environment_alone_does_not_change_legacy_default_routing(tmp_path, monkeypatch, structured_dispatch):
    monkeypatch.setenv("ST_BROWSER_OWNER", "new-agent")
    assert browser.run_registered(_v2_record(), ["observe"], _context(tmp_path)) == 7
    assert structured_dispatch[0]["args"] == ["--session", "st-local-ai"]
    assert not structured_dispatch[0]["launch"].get("managed_session")


def test_named_checks_remain_isolated_without_managed_session(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    request, needs_lock = browser._build_request(["check", "--session", "research", "https://example.test"], _context(tmp_path))
    assert needs_lock
    check = cast(dict[str, object], request["check"])
    launch = cast(dict[str, object], request["launch"])
    assert check["session"] == "research"
    assert launch["isolation_root"]
    assert not launch.get("managed_session")


def test_managed_conflict_is_actionable_without_retry_or_fallback(tmp_path, monkeypatch, structured_dispatch, capsys):
    attempts = []
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda _record, argv, **kwargs: attempts.append(json.loads(argv[1])) or 75)
    assert browser.run_registered(_v2_record(), ["--session", "research", "snapshot"], _context(tmp_path)) == 75
    assert len(attempts) == 1
    captured = capsys.readouterr()
    assert "BROWSER_SESSION_CONFLICT session=research" in captured.out + captured.err
    assert "session status research" in captured.out + captured.err
    assert "session create NEW_NAME" in captured.out + captured.err


@pytest.mark.parametrize("argv", [["--profile", "AI", "--session", "research", "snapshot"], ["--session", "research", "snapshot", "--cdp", "9222"], ["--session", "research", "close", "--all"]])
def test_managed_core_requests_cannot_override_owner_launch_authority(tmp_path, monkeypatch, argv):
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/bin/agent-browser")
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), argv, _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("args,expected", [
    (["--full", "page.png"], ["--full", "ABS/page.png"]),
    (["--annotate", "page.png"], ["--annotate", "ABS/page.png"]),
    (["--if-changed", "--threshold", ".01"], ["--if-changed", "--threshold", ".01"]),
    (["--if-changed", "--threshold=.01", "page.png"], ["--if-changed", "--threshold=.01", "ABS/page.png"]),
    (["#main", "page.png"], ["#main", "ABS/page.png"]),
    (["@e2", "page.png"], ["@e2", "ABS/page.png"]),
    (["--full", "#main", "page.png"], ["--full", "#main", "ABS/page.png"]),
    (["--screenshot-dir", "shots", "--screenshot-format=jpeg", "--screenshot-quality", "80"], ["--screenshot-dir", "ABS/shots", "--screenshot-format=jpeg", "--screenshot-quality", "80"]),
    (["--full", "--annotate", "--json"], ["--full", "--annotate", "--json"]),
    (["@e2"], ["@e2"]), ([".card"], [".card"]),
])
def test_screenshot_parser_preserves_flags_selectors_and_option_values(monkeypatch, args, expected):
    monkeypatch.setattr(browser, "_absolute_local_output_path", lambda path: f"ABS/{path}")
    assert browser._with_resolved_local_screenshot_path(["--session", "selected", "screenshot", *args], "screenshot") == ["--session", "selected", "screenshot", *expected]


@pytest.fixture
def workflow_files(tmp_path):
    definition = tmp_path / "definition.json"
    definition.write_text(json.dumps({"id": "fixture", "steps": [
        {"id": "navigate", "actions": [["open", "{{target}}/page/{{number}}"], ["fill", "@e2", "{{message}}"]]},
        {"id": "finish", "actions": [["screenshot", "--full", "page.png"]], "observation": {"screenshot": "observed.png"}},
    ]}))
    parameters = tmp_path / "parameters.json"
    parameters.write_text(json.dumps({"target": "https://example.test", "number": 2, "message": "Hello world"}))
    return definition, parameters


def test_workflow_run_reads_files_and_normalizes_nested_navigation_only_parameters(tmp_path, monkeypatch, structured_dispatch, workflow_files):
    definition, parameters = workflow_files
    monkeypatch.setattr(browser, "_local_ai_command_lock", lambda: pytest.fail("workflow acquired singleton lock"))
    argv = ["--session", "research", "workflow", "run", "--file", str(definition), "--parameters", str(parameters), "--run-id", "run-1"]
    assert browser.run_registered(_v2_record(), argv, _context(tmp_path)) == 7
    request = structured_dispatch[0]
    assert request["operation"] == "workflow"
    assert request["contract_version"] == 2
    assert request["launch"]["managed_session"] == "research"
    assert request["args"] == ["--session", "research"]
    payload = request["payload"]
    assert set(payload) == {"action", "definition", "parameters", "run_id", "resolution"}
    assert payload["action"] == "run"
    assert payload["run_id"] == "run-1"
    assert payload["resolution"] is None
    assert payload["parameters"] == {"target": "https://example.test", "number": 2, "message": "Hello world"}
    steps = payload["definition"]["steps"]
    assert steps[0]["actions"] == [["open", "https://example.test/page/2"], ["fill", "@e2", "{{message}}"]]
    assert steps[1]["actions"] == [["screenshot", "--full", str(tmp_path / "page.png")]]
    assert steps[1]["observation"]["screenshot"] == str(tmp_path / "observed.png")


@pytest.mark.parametrize("tail,action,resolution", [
    (["resume", "run-1"], "resume", None),
    (["resume", "run-1", "--step", "save", "--resolution", "completed"], "resume", {"step": "save", "outcome": "completed"}),
    (["resume", "run-1", "--step=save", "--resolution=retry"], "resume", {"step": "save", "outcome": "retry"}),
    (["status", "run-1"], "status", None), (["cancel", "run-1"], "cancel", None),
])
def test_workflow_lifecycle_forwards_exact_wire_without_host_lock(tmp_path, structured_dispatch, tail, action, resolution):
    assert browser.run_registered(_v2_record(), ["--session=research", "workflow", *tail], _context(tmp_path)) == 7
    assert structured_dispatch[0]["payload"] == {"action": action, "definition": None, "parameters": {}, "run_id": "run-1", "resolution": resolution}


@pytest.mark.parametrize("prefix", [[], ["--session", "st-local-ai"], ["--proxmox", "--session", "research"]])
def test_workflow_requires_explicit_local_managed_session(tmp_path, monkeypatch, prefix):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), [*prefix, "workflow", "status", "run-1"], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("tail", [
    [], ["unknown"], ["run", "--run-id", "run-1"], ["status"], ["cancel", "run-1", "trailing"],
    ["resume", "run-1", "--step", "save"], ["resume", "run-1", "--resolution", "retry"],
    ["resume", "run-1", "--step", "save", "--resolution", "unknown"],
    ["status", "run-1", "--step", "save"], ["run", "--file=missing", "--run-id="],
])
def test_workflow_rejects_malformed_syntax_before_dispatch(tmp_path, monkeypatch, tail):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["--session", "research", "workflow", *tail], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("action", [["open", "https://example.test", "--cdp=9222"], ["close", "--all"], ["session", "other"], ["snapshot", "--idle-timeout=500"]])
def test_workflow_nested_actions_cannot_override_host_authority(tmp_path, monkeypatch, action):
    definition = tmp_path / "definition.json"
    definition.write_text(json.dumps({"steps": [{"id": "unsafe", "actions": [action]}]}))
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["--session", "research", "workflow", "run", "--file", str(definition), "--run-id", "run-1"], _context(tmp_path))
    assert exc.value.exit_code == 2


def test_workflow_parameters_are_substituted_before_project_route_resolution(tmp_path, monkeypatch, structured_dispatch):
    definition = tmp_path / "definition.json"
    definition.write_text(json.dumps({"steps": [{"id": "navigate", "actions": [["goto", "{{project}}"]]}]}))
    observed = []
    monkeypatch.setattr(browser, "resolve_browser_location", lambda value: observed.append(value) or "https://project.test")
    assert browser.run_registered(_v2_record(), ["--session", "research", "workflow", "run", "--file", str(definition), "--parameters", '{"project":"fixture"}', "--run-id", "run-1"], _context(tmp_path)) == 7
    assert observed == ["fixture"]
    assert structured_dispatch[0]["payload"]["definition"]["steps"][0]["actions"] == [["goto", "https://project.test"]]


def test_workflow_unknown_navigation_parameter_fails_before_dispatch(tmp_path, monkeypatch, workflow_files):
    definition, _parameters = workflow_files
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["--session", "research", "workflow", "run", "--file", str(definition), "--run-id", "run-1"], _context(tmp_path))
    assert exc.value.exit_code == 2


def test_workflow_screenshot_parameters_are_substituted_before_path_resolution_without_rewriting_export(tmp_path, structured_dispatch):
    definition = tmp_path / "recorded.json"
    exported = json.dumps({"steps": [{
        "id": "capture", "actions": [["get", "url"]],
        "screenshot": "{{screenshot_path}}", "observation": {"screenshot": "shots/{{number}}.png"},
    }]})
    definition.write_text(exported)
    absolute = str(tmp_path / "elsewhere" / "replay.png")
    parameters = json.dumps({"screenshot_path": absolute, "number": 2})
    assert browser.run_registered(_v2_record(), ["--session", "research", "workflow", "run", "--file", str(definition), "--parameters", parameters, "--run-id", "replay-1"], _context(tmp_path)) == 7
    step = structured_dispatch[0]["payload"]["definition"]["steps"][0]
    assert step["screenshot"] == absolute
    assert step["observation"]["screenshot"] == str(tmp_path / "shots" / "2.png")
    assert definition.read_text() == exported


@pytest.mark.parametrize("field", ["screenshot", "observation"])
@pytest.mark.parametrize("parameters", [{}, {"path": {"nested": "path.png"}}])
def test_workflow_invalid_screenshot_parameter_fails_before_dispatch(tmp_path, monkeypatch, field, parameters):
    step = {"id": "capture", "actions": [["get", "url"]], field: "{{path}}" if field == "screenshot" else {"screenshot": "{{path}}"}}
    definition = tmp_path / "recorded.json"
    definition.write_text(json.dumps({"steps": [step]}))
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["--session", "research", "workflow", "run", "--file", str(definition), "--parameters", json.dumps(parameters), "--run-id", "replay-1"], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("tail,payload", [
    (["list", "--all"], {"action": "list", "all": True}),
    (["view", "research"], {"action": "view", "name": "research"}),
    (["lease", "research"], {"action": "lease", "name": "research"}),
])
def test_operator_session_reads_and_human_lease_wire(tmp_path, structured_dispatch, tail, payload):
    assert browser.run_registered(_v2_record(), ["session", *tail], _context(tmp_path)) == 7
    assert structured_dispatch[0]["payload"] == payload


@pytest.mark.parametrize("action", ["record-start", "record-stop"])
def test_workflow_recording_requires_explicit_managed_session(tmp_path, structured_dispatch, action):
    assert browser.run_registered(_v2_record(), ["--session", "research", "workflow", action, "record-1"], _context(tmp_path)) == 7
    payload = {"action": action, "definition": None, "parameters": {}, "run_id": "record-1", "resolution": None}
    if action == "record-stop":
        payload["output"] = None
    assert structured_dispatch[0]["payload"] == payload


def test_record_stop_resolves_output_and_reads_parameter_file(tmp_path, structured_dispatch):
    parameters = tmp_path / "parameters.json"
    parameters.write_text('{"target":"https://fixture.test"}')
    assert browser.run_registered(_v2_record(), ["--session", "research", "workflow", "record-stop", "record-1", "--file", str(tmp_path / "record.json"), "--parameters", str(parameters)], _context(tmp_path)) == 7
    assert structured_dispatch[0]["payload"]["output"] == str(tmp_path / "record.json")
    assert structured_dispatch[0]["payload"]["parameters"] == {"target": "https://fixture.test"}


@pytest.mark.parametrize("selected", [None, "st-local-ai", "isolated-fixture"])
@pytest.mark.parametrize("flag", ["", "1"])
def test_managed_extension_fixture_debugging_is_explicit_and_isolated(monkeypatch, selected, flag):
    from cli.lib import browser_policy

    env = {"ST_BROWSER_LOCAL_CHROME": "/bin/chrome", "ST_BROWSER_MANAGED_EXTENSION_TEST": flag}
    launch = browser_policy.managed_session_launch(selected, agent_browser_bin="/bin/agent-browser", env=env)
    prefix = cast(list[str], launch["prefix"])
    enabled = "--enable-unsafe-extension-debugging" in prefix[prefix.index("--args") + 1]
    assert enabled is (selected == "isolated-fixture" and flag == "1")


def test_selected_tab_core_action_routes_through_v2_run_without_launch_or_host_lock(tmp_path, structured_dispatch, monkeypatch):
    handle = "a" * 32
    monkeypatch.setenv("AGENT_BROWSER_SESSION", "unrelated")
    assert browser.run_registered(_v2_record(), ["--selected-tab", handle, "fill", "@e2", "literal text"], _context(tmp_path)) == 7
    request = structured_dispatch[0]
    assert request["operation"] == "run" and request["target"] == "selected-tab"
    assert request["contract_version"] == 2 and request["command"] == "run"
    assert request["args"] == ["--session", f"sel-{handle}"]
    assert request["payload"] == {"actions": [["fill", "@e2", "literal text"]]}
    assert request["launch"]["selected_tab"] == handle
    assert request["launch"]["prefix"] == [] and request["endpoint"] is None
    assert request["check"] is None and request["default_viewport"] is None


def test_selected_tab_navigation_resolves_project_before_bridge_authority_check(tmp_path, structured_dispatch, monkeypatch):
    monkeypatch.setattr(browser, "resolve_browser_location", lambda value: "https://fixture.test/project" if value == "project" else value)
    assert browser.run_registered(_v2_record(), ["--selected-tab=" + "b" * 32, "navigate", "project"], _context(tmp_path)) == 7
    assert structured_dispatch[0]["payload"] == {"actions": [["navigate", "https://fixture.test/project"]]}


@pytest.mark.parametrize("tail,payload", [
    (["list"], {"action": "list"}), (["capabilities"], {"action": "capabilities"}),
    (["revoke", "a" * 32], {"action": "revoke", "handle": "a" * 32}),
])
def test_selected_tabs_discovery_and_revoke_have_no_selected_launch(tmp_path, structured_dispatch, tail, payload):
    assert browser.run_registered(_v2_record(), ["selected-tabs", *tail], _context(tmp_path)) == 7
    request = structured_dispatch[0]
    assert request["operation"] == "selected-tabs" and request["target"] == "selected-tab"
    assert request["payload"] == payload and request["args"] == []
    assert request["launch"]["selected_tab"] is None and request["launch"]["prefix"] == []
    assert request["endpoint"] is None


@pytest.mark.parametrize("tail", [
    ["session", "list"], ["workflow", "status", "id"], ["check", "https://fixture.test"],
    ["--session", "other", "snapshot"], ["--proxmox", "snapshot"], ["--local-ai", "snapshot"],
    ["--engine", "chrome", "snapshot"], ["connect", "https://fixture.test"], ["close", "--all"],
    ["click", "@e1", "--cdp", "9222"], ["step", "open", "https://fixture.test", "--profile", "other"],
])
def test_selected_tabs_deny_session_launch_and_workflow_overrides(tmp_path, monkeypatch, tail):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    with pytest.raises(typer.Exit) as exc:
        browser.run_registered(_v2_record(), ["--selected-tab", "c" * 32, *tail], _context(tmp_path))
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("argv", [
    ["--selected-tab", "short", "snapshot"], ["--selected-tab=" + "A" * 32, "snapshot"],
    ["--selected-tab"], ["snapshot", "--selected-tab", "a" * 32],
    ["--selected-tab", "a" * 32, "--selected-tab", "b" * 32, "snapshot"],
])
def test_selected_tab_handle_is_explicit_opaque_and_unique(tmp_path, monkeypatch, argv):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    assert browser.run_registered(_v2_record(), argv, _context(tmp_path)) == 2


def test_selected_tab_requires_owner_capability_before_dispatch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("cli.extensions.dispatch_extension", _forbid_dispatch)
    assert browser.run_registered(_v2_record(("run",)), ["--selected-tab", "a" * 32, "snapshot"], _context(tmp_path)) == 2
    assert "does not support selected-tab" in capsys.readouterr().err
