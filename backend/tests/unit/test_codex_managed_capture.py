"""Durability and routing tests: no model, provider, or external target calls."""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/lib"))
outbox_module = importlib.import_module("codex_managed_outbox")
capture_module = importlib.import_module("codex_managed_capture")
delivery_module = importlib.import_module("codex_managed_delivery")


@pytest.fixture
def outbox(tmp_path):
    result = outbox_module.ManagedOutbox(tmp_path / "private/outbox.sqlite", max_bytes=100_000, retention_seconds=0)
    result.add_thread("thread", "summitflow", {"namespace": "fixture", "source_kind": "app_server", "producer_id": "owner", "epoch": "epoch", "collector_id": "fixture", "provider_version": "fixture", "schema_fingerprint": "fixture", "thread_id": "thread"})
    return result


def receipt(position=0, source="source"):
    return {"schema_version": "native-observation.v1", "source_id": source, "committed_position": position, "authenticity": "collector_attested"}


def acknowledgement(position=1, *, committed=None, disposition="retained", source="source"):
    return {**receipt(position if committed is None else committed, source), "dispositions": [{"position": position, "disposition": disposition, "issue_code": "receipt_payload_conflict" if disposition == "conflict" else None}]}


def test_capture_survives_restart_and_ack_loss_without_changing_epoch(outbox):
    before = outbox.owner()
    outbox.capture("thread", kind="app_server_event", payload={"method": "test", "params": {"sensitive": "private"}})
    reopened = outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0)
    assert reopened.owner()["epoch"] == before["epoch"]
    assert reopened.pending("thread") == outbox.pending("thread")
    reopened.bind_source("thread", receipt(1))  # remote commit, response lost
    assert reopened.pending("thread") is not None
    assert reopened.accept("thread", 1, acknowledgement(disposition="replayed"))
    assert reopened.pending("thread") is None
    assert "private" not in reopened.path.read_bytes().decode(errors="ignore")
    assert reopened.capture("thread", kind="capture_health", payload={"state": "connected"}) == 2
    assert outbox.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("committed", [0])
def test_gaps_and_stale_acknowledgements_keep_pending_raw(outbox, committed):
    outbox.capture("thread", kind="capture_health", payload={"state": "connected"})
    outbox.bind_source("thread", receipt())
    assert not outbox.accept("thread", 1, acknowledgement(committed=committed))
    assert outbox.pending("thread")["position"] == 1
    assert outbox.status()["delivery_health"] == "acknowledgement_gap"


@pytest.mark.parametrize("bad", ["wrong_source", "future_position", "missing_disposition", "wrong_receipt"])
def test_invalid_acknowledgements_never_advance_delivery(outbox, bad):
    outbox.capture("thread", kind="capture_health", payload={"state": "connected"})
    outbox.bind_source("thread", receipt())
    result = acknowledgement()
    if bad == "wrong_source":
        result["source_id"] = "other"
    elif bad == "future_position":
        result["committed_position"] = 999
    elif bad == "missing_disposition":
        result["dispositions"] = []
    else:
        result["dispositions"][0]["position"] = 2
    with pytest.raises(ValueError):
        outbox.accept("thread", 1, result)
    assert outbox.pending("thread") is not None
    assert outbox.threads()[0]["acknowledged"] == 0


def test_conflict_keeps_original_raw_and_does_not_acknowledge(outbox):
    outbox.capture("thread", kind="capture_health", payload={"state": "connected"})
    outbox.bind_source("thread", receipt())
    original = outbox.pending("thread")
    assert not outbox.accept("thread", 1, acknowledgement(disposition="conflict"))
    assert outbox.pending("thread") == original
    assert outbox.status()["delivery_health"] == "receipt_conflict"


def test_quota_never_evicts_unaccepted_evidence_and_records_gap(outbox):
    outbox.max_bytes = outbox.status()["used_bytes"] + 400
    outbox.capture("thread", kind="capture_health", payload={"state": "connected"})
    original = outbox.pending("thread")
    with pytest.raises(outbox_module.OutboxFull):
        outbox.capture("thread", kind="app_server_event", payload={"raw": "s" * 1000})
    assert outbox.pending("thread") == original
    assert outbox.status()["health"] == "outbox_full"
    assert outbox.status()["capture_gaps"] == 1


def test_ownership_catalog_and_quarantine_share_the_outbox_quota(outbox):
    outbox.max_bytes = outbox.status()["used_bytes"]
    with pytest.raises(outbox_module.OutboxFull):
        outbox.add_thread("extra", "summitflow", {"thread_id": "extra"})
    with pytest.raises(outbox_module.OutboxFull):
        outbox.quarantine({"method": "future"})
    assert len(outbox.threads()) == 1


def test_outbox_never_changes_permissions_on_a_shared_existing_directory(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="private owned directory"):
        outbox_module.ManagedOutbox(shared / "spool.sqlite", max_bytes=1000, retention_seconds=0)
    assert shared.stat().st_mode & 0o777 == 0o755
    assert not (shared / "spool.sqlite").exists()


def test_oversized_transport_preserves_the_owned_native_process(tmp_path, monkeypatch):
    binary = tmp_path / "native-fixture"
    binary.write_text("#!/usr/bin/env python3\nimport sys\nfor line in sys.stdin.buffer:\n sys.stdout.buffer.write(line); sys.stdout.buffer.flush()\n")
    binary.chmod(0o700)
    monkeypatch.setattr(capture_module, "conformance", lambda *_, **__: ("fixture", "fixture", {}))
    outbox = outbox_module.ManagedOutbox(tmp_path / "private/spool.sqlite", max_bytes=256, retention_seconds=0)
    read_fd, write_fd = os.pipe()
    wire = json.dumps({"id": 1, "method": "turn/start", "params": {"input": "x" * 1024}}).encode() + b"\n"
    os.write(write_fd, wire)
    os.close(write_fd)
    output = io.BytesIO()
    with os.fdopen(read_fd, "rb") as input_stream:
        assert capture_module.supervise(outbox, project="fixture", namespace="fixture", binary=str(binary), input_stream=input_stream, output_stream=output) == 0
    assert output.getvalue() == wire
    assert outbox.status()["health"] == "outbox_full"
    assert outbox.status()["capture_gaps"] >= 1


def test_process_and_delivery_leases_fence_competing_owners(outbox):
    with outbox.lease(), pytest.raises(BlockingIOError), outbox.lease():
        pass
    with outbox.delivery_lease(), pytest.raises(BlockingIOError), outbox.delivery_lease():
        pass


def validators():
    with zipfile.ZipFile(ROOT / "docker/workspace-packages/agent_hub_client-0.4.1-py3-none-any.whl") as wheel:
        return {name: Draft7Validator(json.loads(wheel.read(f"agent_hub/codex_protocol/{name}.json"))) for name in ("ServerRequest", "ServerNotification")}


def collector(outbox):
    return capture_module.ManagedCapture(outbox, project="summitflow", namespace="fixture", version="fixture", fingerprint="fixture", validators=validators())


def test_external_threads_are_rejected_and_capture_defaults_off(outbox, monkeypatch):
    monkeypatch.delenv("SUMMITFLOW_CODEX_MANAGED_CAPTURE", raising=False)
    assert capture_module.capture_enabled() is False
    capture = collector(outbox)
    rejection = capture.client_message({"id": 1, "method": "thread/resume", "params": {"threadId": "external"}})
    assert rejection["error"]["message"] == "thread_is_not_owned_by_this_managed_session"
    assert outbox.status()["pending"] == 0
    assert capture.client_message({"id": 2, "method": "thread/resume", "params": {"threadId": "thread"}}) is None


def test_live_approval_is_spooled_before_authority_response_and_never_replayed(outbox):
    capture = collector(outbox)
    request = {"id": 99, "method": "item/commandExecution/requestApproval", "params": {"threadId": "thread", "turnId": "turn", "itemId": "item", "startedAtMs": 0}}
    capture.server_message(request)
    assert outbox.pending("thread")["payload"] == request
    # Capture returns no decision; the owning client supplies the response.
    assert capture.client_message({"id": 99, "result": {"decision": "decline"}}) is None
    capture.server_message({"method": "serverRequest/resolved", "params": {"threadId": "thread", "requestId": 99}})
    assert not capture.approvals
    with outbox.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT observation FROM events ORDER BY position")]
    assert [r["kind"] for r in rows] == ["app_server_event", "approval_response", "app_server_event"]
    assert rows[1]["source_reference"] == {"connection_id": capture.connection_id, "request_id": 99, "turn_id": "turn", "item_id": "item"}
    restarted = collector(outbox)
    assert restarted.approvals == {}  # retained evidence is never an execution queue


def test_unsupported_event_retains_raw_and_fails_capture_visibly(outbox):
    capture = collector(outbox)
    wire = {"method": "item/future", "params": {"threadId": "thread", "sensitive": "retained"}}
    capture.server_message(wire)
    assert outbox.pending("thread")["payload"] == wire
    assert capture.capturing is False
    assert outbox.status()["health"] == "unsupported"


def test_snapshots_and_fork_history_are_never_live_command_events(outbox):
    capture = collector(outbox)
    capture.client_message({"id": 1, "method": "thread/fork", "params": {"threadId": "thread"}})
    capture.server_message({"id": 1, "result": {"thread": {"id": "child", "sessionId": "root", "turns": [{"id": "parent-turn", "items": [{"id": "parent-command"}]}]}}})
    with outbox.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT observation FROM events WHERE thread='child' ORDER BY position")]
    assert [r["kind"] for r in rows] == ["capture_health", "app_server_snapshot"]
    assert rows[1]["origin"] == "stored_snapshot"
    assert rows[1]["source_reference"]["parent_thread_id"] == "thread"


@pytest.mark.asyncio
async def test_agent_hub_downtime_and_lost_ack_resume_exact_receipt(outbox, monkeypatch):
    # Exercise the packaged public models while the host SDK may precede rebuild.
    module = types.ModuleType("agent_hub.models.native_observation")
    with zipfile.ZipFile(ROOT / "docker/workspace-packages/agent_hub_client-0.4.1-py3-none-any.whl") as wheel:
        exec(compile(wheel.read("agent_hub/models/native_observation.py"), "native_observation.py", "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    original = {"method": "turn/completed", "params": {"threadId": "thread", "turn": {"id": "turn", "items": [], "status": "completed"}}}
    outbox.capture("thread", kind="app_server_event", payload=original)
    sent = []

    class Client:
        calls = 0

        async def get_session(self, thread):
            assert thread == "thread"
            return SimpleNamespace(project_id="summitflow", provider="codex", provider_metadata={})

        async def register_native_source(self, thread, registration, **kwargs):
            assert kwargs["execution_owner_secret"] == "fixture"
            return SimpleNamespace(source_id="source", model_dump=lambda **_: receipt(min(self.calls, 1)))

        async def ingest_native_observations(self, thread, source, batch, **kwargs):
            del thread, source, kwargs
            self.calls += 1
            sent.append(batch.observations[0].model_dump(mode="json"))
            if self.calls == 1:
                raise ConnectionError("response lost after remote commit")
            return SimpleNamespace(model_dump=lambda **_: acknowledgement(disposition="replayed"))

    client = Client()
    assert await delivery_module.deliver(outbox, client, execution_owner_secret="fixture") == 0
    assert outbox.pending("thread") is not None
    assert await delivery_module.deliver(outbox, client, execution_owner_secret="fixture") == 1
    assert sent[0] == sent[1] and outbox.pending("thread") is None
    assert "private" not in json.dumps(outbox.status())


def test_disabled_capture_has_no_spool_or_sdk_dependency(monkeypatch):
    monkeypatch.delenv("SUMMITFLOW_CODEX_MANAGED_CAPTURE", raising=False)
    monkeypatch.delenv("SUMMITFLOW_CODEX_OUTBOX", raising=False)
    assert not capture_module.capture_enabled()
    assert delivery_module.configured_outbox() is None


def test_runtime_rollback_preserves_native_connection_and_pending_evidence(outbox):
    capture = collector(outbox)
    outbox.capture("thread", kind="capture_health", payload={"state": "connected"})
    outbox.disable_capture()
    assert capture.client_message({"id": 1, "method": "turn/start", "params": {"threadId": "thread", "input": []}}) is None
    assert not capture.capturing and outbox.status()["capture_disabled"]
    count = outbox.status()["pending"]
    capture.server_message({"method": "turn/completed", "params": {"threadId": "thread", "turn": {"id": "turn", "items": [], "status": "completed"}}})
    assert outbox.status()["pending"] == count and outbox.pending("thread") is not None


def test_native_spawn_evidence_owns_child_without_copying_parent_events(outbox):
    capture = collector(outbox)
    event = {"method": "item/completed", "params": {"threadId": "thread", "turnId": "turn", "completedAtMs": 1, "item": {"type": "collabAgentToolCall", "id": "spawn", "tool": "spawnAgent", "status": "completed", "senderThreadId": "thread", "receiverThreadIds": ["child"], "agentsStates": {}}}}
    capture.server_message(event)
    assert "child" in capture.owned
    assert capture.client_message({"id": 1, "method": "thread/resume", "params": {"threadId": "child"}}) is None
    with outbox.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT observation FROM events WHERE thread='child'")]
    assert all(r["kind"] == "capture_health" for r in rows)
    assert rows[-1]["payload"]["reason"] == "native_child_requires_subscription"


def test_unbound_unsupported_frame_is_quarantined_without_attributing_a_subject(outbox):
    capture = collector(outbox)
    capture.server_message({"method": "future", "params": {"unknown": "raw evidence"}})
    assert not capture.capturing and outbox.status()["quarantined"] == 1
    with outbox.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT observation FROM events")]
    assert all(r["kind"] == "capture_health" for r in rows)


def test_legacy_approval_is_explicitly_unattributed_and_never_silently_discarded(outbox):
    capture = collector(outbox)
    wire = {"id": 1, "method": "execCommandApproval", "params": {"conversationId": "thread", "callId": "legacy-call", "command": ["printf", "fixture"], "cwd": "/tmp", "parsedCmd": []}}
    assert capture.validators["ServerRequest"].is_valid(wire)
    capture.server_message(wire)
    assert not capture.capturing and outbox.status()["quarantined"] == 1
    assert outbox.status()["health"] == "unsupported" and not capture.approvals


def test_model_configuration_stays_separate_from_observed_delivery(outbox):
    capture = collector(outbox)
    capture.client_message({"id": 1, "method": "turn/start", "params": {"threadId": "thread", "model": "requested-only", "input": [{"type": "text", "text": "not retained by request capture"}]}})
    raw = outbox.pending("thread")
    assert raw["kind"] == "app_server_configuration"
    assert raw["payload"]["params"] == {"model": "requested-only"}
    assert "observed_model" not in raw and "input" not in raw["payload"]["params"]
