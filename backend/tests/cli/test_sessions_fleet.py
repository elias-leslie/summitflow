"""New fleet commands preserve existing readers and quiet wait semantics."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from st_sdk.fleet import FleetClient
from st_sdk.http import BaseHTTPClient
from typer.testing import CliRunner

from cli.commands import sessions_fleet
from cli.main import app

runner = CliRunner()


def test_wait_defaults_to_300_and_timeout_is_silent(monkeypatch):
    client = MagicMock()
    client.wait.return_value = {"events": [], "cursor": 42}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "wait", "root-fixture", "--cursor", "42"])
    assert result.exit_code == 0
    assert result.output == ""
    client.wait.assert_called_once_with("root-fixture", cursor=42, timeout=300)


def test_send_retains_instruction_and_reports_capability(monkeypatch):
    client = MagicMock()
    client.send.return_value = {"capability": "unavailable", "delivery": "not-attempted", "retained": True}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "send", "root-fixture", "Exact short instruction", "--source-key", "revision:1"])
    assert result.exit_code == 0
    assert "not-attempted" in result.output
    client.send.assert_called_once_with("root-fixture", instruction="Exact short instruction", scope={}, source_key="revision:1")


@pytest.mark.parametrize("agent", ["cc:8ae0f1", "codex:b6c1d2", "pi:0a1b2c", "agy:ffee00", "tmux:243"])
def test_send_to_an_agent_id_defaults_to_the_handshake_ledger(monkeypatch, agent):
    from cli.commands import sessions_handshake

    sent = []
    monkeypatch.setattr(sessions_fleet, "_client", lambda: pytest.fail("agent ids are not fleet roots"))
    monkeypatch.setattr(sessions_handshake, "send_request", lambda root, text: sent.append((root, text)))
    result = runner.invoke(app, ["sessions", "send", agent, "Self-contained ask"])
    assert result.exit_code == 0, result.output
    assert sent == [(agent, "Self-contained ask")]


@pytest.mark.parametrize("command", ["show", "close"])
def test_existing_lifecycle_routes_root_handles(monkeypatch, command):
    client = MagicMock()
    getattr(client, command).return_value = {"root": "root-fixture", "status": "closed"}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", command, "root-fixture"])
    assert result.exit_code == 0
    getattr(client, command).assert_called_once_with("root-fixture")


def test_list_fleet_is_explicit_addition(monkeypatch):
    client = MagicMock()
    client.list.return_value = {"roots": []}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "list", "--fleet", "--project", "neri"])
    assert result.exit_code == 0
    client.list.assert_called_once_with(project_id="neri", limit=20)


def test_public_sdk_append_is_versioned_and_digest_keyed():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"sequence": 1})

    with BaseHTTPClient("http://fixture/api", "fixture", transport=httpx.MockTransport(handle)) as client:
        result = FleetClient(client).append("root-fixture", source_key="neri:run:1:revision:2", event_type="source.changed", attributes={"source_ref": "run:1", "revision": "2"})
    assert result["sequence"] == 1
    assert requests[0].url.path == "/api/fleet/v1/roots/root-fixture/events"
    assert b'"digest"' in requests[0].content


def test_emit_returns_compact_delta_through_public_sdk(monkeypatch):
    client = MagicMock()
    client.append.return_value = {"sequence": 7, "source_key": "source:revision:2"}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "emit", "root-fixture", "support.delta", "--source-key", "source:revision:2", "--attributes", '{"source_ref":"source:2","kind":"impact-change"}'])
    assert result.exit_code == 0
    client.append.assert_called_once_with("root-fixture", source_key="source:revision:2", event_type="support.delta", attributes={"source_ref": "source:2", "kind": "impact-change"})
    invalid = runner.invoke(app, ["sessions", "emit", "root-fixture", "root.closed", "--source-key", "bad", "--attributes", '{}'])
    assert invalid.exit_code != 0
    assert client.append.call_count == 1


@pytest.mark.parametrize("extra,forwarded", [
    ([], {}),
    (["--resume-session", "00000000-0000-4000-8000-000000000001"],
     {"resume_session": "00000000-0000-4000-8000-000000000001"}),
    (["--execution-root", "/workspace/fixture"], {"execution_root": "/workspace/fixture"}),
])
def test_start_forwards_optional_fields_only_when_requested(monkeypatch, extra, forwarded):
    client = MagicMock()
    client.start.return_value = {"root": "root-" + "0" * 32, "status": "registered"}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["-P", "neri", "sessions", "start", "Reconcile state.",
                                 "--request-id", "root-" + "0" * 32, *extra])
    assert result.exit_code == 0, result.output
    client.start.assert_called_once_with(
        project_id="neri", tool="codex", surface="aico", instruction="Reconcile state.", scope={},
        role="portfolio-root", lead_root=None, facet=None, root="root-" + "0" * 32, **forwarded)


def _live_identities(**sessions: str) -> None:
    """Register live coordination identities (anchored on this test process) for agent id -> session."""
    import os

    from cli.lib import coord_lineage, leases

    anchor = f"{os.getpid()}:{leases._process_start(os.getpid())}"
    doc = coord_lineage.load_doc()
    doc["identities"] = {aid.replace("_", ":", 1): {"anchor": anchor, "session": sid} for aid, sid in sessions.items()}
    coord_lineage.save_doc(doc)


def _capture_handshake(monkeypatch) -> list[tuple[str, str]]:
    from cli.commands import sessions_handshake

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(sessions_fleet, "_client", lambda: pytest.fail("labels are not fleet roots"))
    monkeypatch.setattr(sessions_handshake, "send_request", lambda root, text: sent.append((root, text)))
    return sent


def test_send_resolves_a_label_to_the_one_live_agent_it_names(monkeypatch):
    _live_identities(cc_c9ffbd="c9ffbd05-c536-446f-82f7-30690775f33e", codex_8af197="01a12620-c916-7aa1-afa8-f774ce8af197")
    sent = _capture_handshake(monkeypatch)
    # A spawned Codex subagent session resolves to its live root thread's identity.
    monkeypatch.setattr(sessions_fleet, "_agent_hub_sessions", lambda: [
        {"id": "01a12722-79b7-78d2-8d76-f9b9e16f473e", "parent_session_id": "01a12620-c916-7aa1-afa8-f774ce8af197",
         "external_identity": {"display_identity": "Halley", "aico_widget_id": "5695b962"}},
        {"id": "c9ffbd05-c536-446f-82f7-30690775f33e", "tmux_session_name": "aico-867a65c2"},
    ])
    result = runner.invoke(app, ["sessions", "send", "halley", "Self-contained ask"])
    assert result.exit_code == 0, result.output
    assert "→ codex:8af197" in result.output
    assert sent == [("codex:8af197", "Self-contained ask")]
    assert runner.invoke(app, ["sessions", "send", "aico-867a65c2", "Ask two"]).exit_code == 0
    assert runner.invoke(app, ["sessions", "send", "c9ffbd", "Ask three", "--delivery", "handshake"]).exit_code == 0
    assert sent[1:] == [("cc:c9ffbd", "Ask two"), ("cc:c9ffbd", "Ask three")]


def test_send_refuses_a_label_naming_no_or_several_live_agents(monkeypatch):
    _live_identities(cc_c9ffbd="c9ffbd05-c536-446f-82f7-30690775f33e", cc_aa11bb="aa11bb22-0000-4000-8000-000000000000")
    sent = _capture_handshake(monkeypatch)
    monkeypatch.setattr(sessions_fleet, "_agent_hub_sessions", lambda: [
        {"id": "c9ffbd05-c536-446f-82f7-30690775f33e", "external_identity": {"display_identity": "Twin"}},
        {"id": "aa11bb22-0000-4000-8000-000000000000", "external_identity": {"display_identity": "twin"}},
        {"id": "dead0000-0000-4000-8000-000000000000", "external_identity": {"display_identity": "Ghost"}},
    ])
    several = runner.invoke(app, ["sessions", "send", "Twin", "ask"])
    assert several.exit_code == 2
    assert "cc:aa11bb" in several.output and "cc:c9ffbd" in several.output
    none = runner.invoke(app, ["sessions", "send", "neri-bc", "ask"])
    assert none.exit_code == 2 and "names no live agent" in none.output
    ghost = runner.invoke(app, ["sessions", "send", "ghost", "ask"])
    assert ghost.exit_code == 2 and "dead0000" in ghost.output and "no live coordination identity" in ghost.output
    assert sent == []


def test_explicit_fleet_stream_still_reaches_a_custom_fleet_root(monkeypatch):
    client = MagicMock()
    client.send.return_value = {"delivery": "retained"}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    monkeypatch.setattr(sessions_fleet, "_agent_hub_sessions", lambda: pytest.fail("explicit fleet sends never resolve labels"))
    result = runner.invoke(app, ["sessions", "send", "custom-handle", "Instruction", "--delivery", "fleet-stream", "--source-key", "r:1"])
    assert result.exit_code == 0, result.output
    client.send.assert_called_once_with("custom-handle", instruction="Instruction", scope={}, source_key="r:1")


def test_native_thread_to_a_live_tui_wakes_through_the_ledger_not_the_queue(monkeypatch, tmp_path):
    from cli.commands import sessions_native_delivery as native
    from cli.lib import coord, coord_wake

    thread = "01a12620-c916-7aa1-afa8-f774ce8af197"
    _live_identities(codex_8af197=thread)
    monkeypatch.setattr(coord_wake, "STATE", tmp_path)
    monkeypatch.setattr(native, "get_project_root_path", lambda project: str(tmp_path))
    monkeypatch.setattr(native, "verify_thread_binding", lambda *a: {"thread_id": thread})
    monkeypatch.setattr(native, "append_fleet_event", lambda *a, **k: pytest.fail("live threads are not queued"))
    monkeypatch.setattr(native, "WAKE_CONFIRM_SECONDS", 0.3)

    # Busy (no armed idle watcher): recorded and left queued for its next turn hook.
    busy = native.send_native_instruction(thread, "Review the plan", project="p", source_key="r:1")
    assert busy["delivery"] == "queued" and busy["agent_id"] == "codex:8af197" and "not confirmed idle" in busy["reason"]
    assert [(r["to"], r["text"]) for r in coord._load_ledger()] == [("codex:8af197", "Review the plan")]

    # Idle: the armed watcher (stand-in: this process) surfaces it, so the send reports woken.
    import json

    monkeypatch.setattr(coord_wake, "codex_watch_pid", lambda agent: 4242)
    row_id = coord._load_ledger()[0]["id"]
    coord_wake.seen_path("codex:8af197").write_text(json.dumps({f"{row_id}:req": 1.0}))
    woken = native.send_native_instruction(thread, "Review the plan", project="p", source_key="r:1")
    assert woken["delivery"] == "woken" and woken["observed"] and woken["request_id"] == row_id
    assert len(coord._load_ledger()) == 1  # identical open request is not duplicated


def test_native_thread_to_an_offline_thread_still_uses_the_queue(monkeypatch, tmp_path):
    from cli.commands import sessions_native_delivery as native

    monkeypatch.setattr(native, "get_project_root_path", lambda project: str(tmp_path))
    monkeypatch.setattr(native, "verify_thread_binding", lambda *a: {"thread_id": a[0]})
    monkeypatch.setattr(native, "append_fleet_event", lambda *a, **k: {"id": 1, "created": True})
    queued = []
    monkeypatch.setattr(native, "queue_native_thread", lambda *a: queued.append(a) or {"queue_id": "q"})
    result = native.send_native_instruction("01a12620-c916-7aa1-afa8-f774ce8af197", "Resume work", project="p", source_key="r:1")
    assert result["delivery"] == "queued" and "transport" not in result and len(queued) == 1
