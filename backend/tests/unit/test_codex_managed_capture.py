"""Durability and routing tests: no model, provider, or external target calls."""

from __future__ import annotations

import importlib
import io
import json
import os
import sqlite3
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
        return {name: Draft7Validator(json.loads(wheel.read(f"agent_hub/codex_protocol/0.159.3/{name}.json"))) for name in ("ServerRequest", "ServerNotification")}


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
    assert raw["payload"]["params"]["model"] == "requested-only"
    assert raw["payload"]["params"]["clientUserMessageId"]
    assert "observed_model" not in raw and "input" not in raw["payload"]["params"]


def test_protocol_upgrade_keeps_old_pending_stream_and_rotates_only_once(outbox):
    owner = outbox.owner()
    outbox.capture("thread", kind="capture_health", payload={"state": "old"})
    original = outbox.pending("thread", 0)
    outbox.bind_source("thread", receipt(), 0)
    outbox.rotate_protocol(version="codex-cli next", fingerprint="next")
    outbox.rotate_protocol(version="codex-cli next", fingerprint="next")
    assert outbox.capture("thread", kind="capture_health", payload={"state": "new"}) == 1
    streams = outbox.streams()
    assert [stream["generation"] for stream in streams] == [0, 1]
    assert outbox.pending("thread", 0) == original
    assert outbox.pending("thread", 1)["payload"]["state"] == "new"
    assert outbox.predecessor("thread", 1) == "source"
    assert outbox.owner()["producer"] == owner["producer"] and outbox.owner()["epoch"] == owner["epoch"]
    assert outbox.accept("thread", 1, acknowledgement(), 0)
    assert outbox.pending("thread", 1) is not None
    outbox.bind_source("thread", receipt(source="next-source"), 1)
    assert outbox.accept("thread", 1, acknowledgement(source="next-source"), 1)


def test_remote_checkpoint_never_acknowledges_unsent_local_copy(outbox):
    for state in ("one", "two"):
        outbox.capture("thread", kind="capture_health", payload={"state": state})
    outbox.bind_source("thread", receipt())
    assert outbox.accept("thread", 1, acknowledgement(committed=2))
    assert outbox.threads()[0]["acknowledged"] == 1
    assert outbox.pending("thread")["position"] == 2


def test_quarantine_exact_ack_conflict_and_restart(outbox):
    registration = {"project_id": "summitflow", "namespace": "fixture", "producer_id": "owner", "epoch": "epoch", "collector_id": "fixture", "provider_version": "fixture", "schema_fingerprint": "fixture"}
    outbox.quarantine({"method": "future"}, registration=registration, reference={"connection_id": "connection"})
    row = outbox.quarantines()[0]
    outbox.bind_quarantine(row["id"], receipt(source="quarantine"))
    with pytest.raises(ValueError):
        outbox.accept_quarantine(row["id"], acknowledgement(source="other"))
    assert not outbox.accept_quarantine(row["id"], acknowledgement(source="quarantine", disposition="conflict"))
    reopened = outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0)
    assert reopened.quarantines()[0]["payload"] == row["payload"]
    assert reopened.accept_quarantine(row["id"], acknowledgement(source="quarantine", disposition="replayed"))
    assert not reopened.quarantines()
    assert "thread_id" not in json.loads(row["payload"])


def test_quarantine_upgrade_has_distinct_stable_source_positions(outbox):
    for generation in (0, 1, 0):
        outbox.quarantine({"method": "future"}, registration={"project_id": "summitflow", "generation": generation})
    rows = outbox.quarantines()
    assert sorted((json.loads(row["registration"])["generation"], row["position"]) for row in rows) == [(0, 1), (0, 2), (1, 1)]


def test_cleanup_reclaims_physical_pages_and_never_deletes_pending(outbox):
    outbox.max_bytes = 2_000_000
    for _ in range(10):
        outbox.capture("thread", kind="capture_health", payload={"raw": "x" * 50_000})
    before = outbox.path.stat().st_size
    outbox.bind_source("thread", receipt())
    for position in range(1, 10):
        assert outbox.accept("thread", position, acknowledgement(position))
    status = outbox.status()
    assert status["physical_bytes"] < before / 2
    assert status["pending"] == 1 and outbox.pending("thread")["position"] == 10
    assert outbox.capture("thread", kind="capture_health", payload={"state": "after cleanup"}) == 11


def test_safe_reenable_preserves_pending_and_never_replays_decisions(outbox):
    capture = collector(outbox)
    outbox.capture("thread", kind="capture_health", payload={"state": "before"})
    original = outbox.pending("thread")
    outbox.disable_capture()
    capture.refresh_switch()
    outbox.enable_capture()
    capture.refresh_switch()
    assert capture.capturing and capture.failure is None
    assert outbox.pending("thread") == original
    assert outbox.status()["capture_gaps"] > 0
    assert capture.approvals == {} and capture.subscription_queue == []
    # Even during disabled capture the proxy cannot attach an external thread.
    outbox.disable_capture()
    assert capture.client_message({"id": 1, "method": "thread/resume", "params": {"threadId": "external"}})["error"]


def test_explicit_initialization_and_child_subscription_never_start_turns(outbox):
    capture = capture_module.ManagedCapture(outbox, project="summitflow", namespace="fixture", version="fixture", fingerprint="fixture", validators=validators(), enforce_handshake=True)
    assert capture.client_message({"id": 1, "method": "thread/resume", "params": {"threadId": "thread"}})["error"]["code"] == -32002
    assert capture.client_message({"id": 2, "method": "initialize", "params": {"clientInfo": {"name": "fixture", "version": "1"}}}) is None
    capture.server_message({"id": 2, "result": {"userAgent": "fixture"}})
    assert capture.client_message({"method": "initialized"}) is None
    capture.own_thread("child")
    capture.subscribe("child")
    capture.subscribe("child")
    assert len(capture.subscription_queue) == 1
    assert capture.subscription_queue[0]["method"] == "thread/resume"
    capture.subscribe("external")
    assert len(capture.subscription_queue) == 1


def test_operator_actions_are_scoped_to_actual_single_project(outbox, monkeypatch):
    monkeypatch.setattr(delivery_module, "configured_outbox", lambda *_args: outbox)
    monkeypatch.setattr(capture_module, "codex_binary", lambda: (_ for _ in ()).throw(ValueError("unavailable")))
    with pytest.raises(ValueError, match="binding"):
        delivery_module.operator_action("disable", project_id="other")
    assert not outbox.owner()["capture_disabled"]
    assert delivery_module.operator_action("disable", project_id="summitflow")["capture_disabled"]
    result = delivery_module.operator_action("enable", project_id="summitflow")
    assert not result["capture_disabled"] and result["project_id"] == "summitflow"
    assert result["installed_protocol_status"] == "unavailable"
    outbox.add_thread("other-thread", "other", {"thread_id": "other-thread"})
    assert delivery_module.operator_status()["actions"] == []
    with pytest.raises(ValueError, match="binding"):
        delivery_module.operator_action("disable", project_id="summitflow")


@pytest.mark.parametrize("disposition", ["quarantined", "replayed"])
def test_first_quarantine_disposition_is_a_durable_acceptance(outbox, disposition):
    outbox.quarantine({"method": "future"}, registration={"project_id": "summitflow"})
    row = outbox.quarantines()[0]
    outbox.bind_quarantine(row["id"], receipt())
    assert outbox.accept_quarantine(row["id"], acknowledgement(disposition=disposition))
    assert outbox.status()["quarantined"] == 0


@pytest.mark.parametrize("failure", ["unsupported", "rotation_full"])
def test_startup_failure_with_full_spool_preserves_native_execution(outbox, tmp_path, monkeypatch, failure):
    binary = tmp_path / "native-fixture"
    binary.write_text("#!/usr/bin/env python3\nimport sys\nfor line in sys.stdin.buffer:\n sys.stdout.buffer.write(line); sys.stdout.buffer.flush()\n")
    binary.chmod(0o700)
    outbox.max_bytes = outbox.status()["used_bytes"]
    if failure == "unsupported":
        monkeypatch.setattr(capture_module, "conformance", lambda *_, **__: (_ for _ in ()).throw(ValueError("unsupported")))
    else:
        monkeypatch.setattr(capture_module, "conformance", lambda *_, **__: ("next", "next", {}))
    read_fd, write_fd = os.pipe()
    wire = b'{"id":1,"method":"initialize","params":{}}\n'
    os.write(write_fd, wire)
    os.close(write_fd)
    output = io.BytesIO()
    with os.fdopen(read_fd, "rb") as input_stream:
        assert capture_module.supervise(outbox, project="summitflow", namespace="fixture", binary=str(binary), input_stream=input_stream, output_stream=output) == 0
    assert output.getvalue() == wire
    assert outbox.status()["health"] in {"unsupported", "outbox_full"}
    assert outbox.threads()[0]["generation"] == 0


def test_managed_client_correlation_is_opaque_and_preserves_existing_authority_ids(outbox):
    capture = collector(outbox)
    missing = {"id": 1, "method": "turn/start", "params": {"threadId": "thread", "input": []}}
    assert capture.client_message(missing) is None
    assert capture.client_modified and missing["params"]["clientUserMessageId"]
    for provided in ("caller-supplied", None):
        wire = {"id": 2, "method": "turn/steer", "params": {"threadId": "thread", "clientUserMessageId": provided}}
        assert capture.client_message(wire) is None
        assert wire["params"]["clientUserMessageId"] == provided and not capture.client_modified


@pytest.mark.parametrize("fault", ["INSERT OR IGNORE INTO events_v2", "ALTER TABLE events_v2"])
def test_schema_migration_failure_restores_original_pending_receipts(outbox, monkeypatch, fault):
    outbox.capture("thread", kind="capture_health", payload={"private": "original"})
    original = outbox.pending("thread")
    with outbox.connect() as db:
        db.execute("ALTER TABLE events RENAME TO prior_events")
        db.execute("CREATE TABLE events(thread TEXT,position INTEGER,observation TEXT,byte_size INTEGER,accepted_at REAL,disposition TEXT,issue TEXT,PRIMARY KEY(thread,position))")
        db.execute("INSERT INTO events SELECT thread,position,observation,byte_size,accepted_at,disposition,issue FROM prior_events")
        db.execute("DROP TABLE prior_events")
    connect = sqlite3.connect
    class FaultConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith(fault):
                raise sqlite3.OperationalError("injected migration interruption")
            return super().execute(sql, *args, **kwargs)
    with monkeypatch.context() as injected:
        injected.setattr(outbox_module.sqlite3, "connect", lambda *a, **k: connect(*a, **k, factory=FaultConnection))
        with pytest.raises(sqlite3.OperationalError):
            outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0)
    reopened = outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0)
    assert reopened.pending("thread") == original


def test_constructor_recovers_prior_interrupted_legacy_table_without_losing_raw(outbox):
    outbox.capture("thread", kind="capture_health", payload={"private": "original"})
    original = outbox.pending("thread")
    with outbox.connect() as db:
        db.execute("ALTER TABLE events RENAME TO legacy_events")
    reopened = outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0)
    assert reopened.pending("thread") == original
    with reopened.connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_events'").fetchone()


def test_concurrent_constructors_preserve_exact_pending_envelope(outbox):
    from concurrent.futures import ThreadPoolExecutor

    outbox.capture("thread", kind="capture_health", payload={"private": "original"})
    original = outbox.pending("thread")
    def reopen(_):
        return outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0).pending("thread")
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(reopen, range(8))) == [original] * 8


@pytest.mark.parametrize("configuration", [None, KeyError("quota"), ValueError("policy"), sqlite3.OperationalError("storage"), outbox_module.OutboxFull("quota")])
def test_managed_entrypoint_policy_failure_preserves_native_launch(tmp_path, monkeypatch, configuration):
    import importlib.util

    spec = importlib.util.spec_from_file_location("managed_entrypoint_fixture", ROOT / "scripts/codex-managed-session.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "project.identity.json").write_text(json.dumps({"project": {"id": "fixture"}}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "capture_enabled", lambda: True)
    monkeypatch.setattr(module, "codex_binary", lambda: "/fixture/codex")
    monkeypatch.delenv("SUMMITFLOW_CODEX_OUTBOX", raising=False)
    def configured(_project=None):
        if isinstance(configuration, Exception):
            raise configuration
        return configuration
    monkeypatch.setattr(module, "configured_outbox", configured)
    commands = []
    class ExecCalled(Exception):
        pass
    def execute(binary, args):
        commands.append((binary, args))
        raise ExecCalled
    monkeypatch.setattr(module.os, "execv", execute)
    with pytest.raises(ExecCalled):
        module.main(["--project", "fixture", "--project-root", str(tmp_path)])
    assert commands == [("/fixture/codex", ["/fixture/codex", "app-server", "--listen", "stdio://"])]


def test_bad_policy_fallback_still_fences_a_competing_configured_owner(outbox, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("managed_entrypoint_fixture", ROOT / "scripts/codex-managed-session.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("SUMMITFLOW_CODEX_OUTBOX", str(outbox.path))
    monkeypatch.setattr(module.os, "execv", lambda *_args: pytest.fail("Competing owner must not launch"))
    with outbox.lease(), pytest.raises(BlockingIOError):
        module.native_fallback("/fixture/codex")


@pytest.mark.asyncio
async def test_delivery_rollout_registration_retains_original_profile_across_upgrade(outbox, monkeypatch):
    module = types.ModuleType("agent_hub.models.native_observation")
    with zipfile.ZipFile(ROOT / "docker/workspace-packages/agent_hub_client-0.4.1-py3-none-any.whl") as wheel:
        exec(compile(wheel.read("agent_hub/models/native_observation.py"), "native_observation.py", "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    outbox.capture("thread", kind="capture_health", payload={"state": "old"})
    outbox.rotate_protocol(version="next", fingerprint="next-fingerprint")
    outbox.capture("thread", kind="capture_health", payload={"state": "new"})
    registrations = []
    class Client:
        async def get_session(self, _thread):
            return SimpleNamespace(project_id="summitflow", provider="codex", provider_metadata={"transcript_path": "/owned/rollout.jsonl"})
        async def register_native_source(self, _thread, registration, **_kwargs):
            registrations.append(registration)
            source = "old" if registration.generation == 0 else "new"
            return SimpleNamespace(source_id=source, model_dump=lambda **_: receipt(source=source))
        async def ingest_native_observations(self, _thread, source, _batch, **_kwargs):
            return SimpleNamespace(model_dump=lambda **_: acknowledgement(source=source))
    assert await delivery_module.deliver(outbox, Client(), execution_owner_secret="fixture") == 2
    rollout = [registration for registration in registrations if registration.source_kind == "rollout"]
    assert len(rollout) == 1 and rollout[0].provider_version == "fixture" and rollout[0].generation == 0
    successor = next(registration for registration in registrations if registration.generation == 1)
    assert successor.provider_version == "next" and successor.predecessor_source_id == "old"
    assert outbox.status()["pending"] == 0


@pytest.mark.asyncio
async def test_quarantine_lost_ack_replays_exact_original_without_subject(outbox, monkeypatch):
    module = types.ModuleType("agent_hub.models.native_observation")
    with zipfile.ZipFile(ROOT / "docker/workspace-packages/agent_hub_client-0.4.1-py3-none-any.whl") as wheel:
        exec(compile(wheel.read("agent_hub/models/native_observation.py"), "native_observation.py", "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    outbox.quarantine({"method": "future", "params": {"private": "raw"}}, registration={"project_id": "summitflow", "namespace": "fixture", "producer_id": "owner", "epoch": "epoch", "collector_id": "fixture", "provider_version": "fixture", "schema_fingerprint": "fixture"}, reference={"connection_id": "original"})
    sent = []
    class Client:
        async def get_session(self, _thread):
            return SimpleNamespace(project_id="summitflow", provider="codex", provider_metadata={})
        async def register_native_source(self, *_args, **_kwargs):
            return SimpleNamespace(source_id="source", model_dump=lambda **_: receipt())
        async def register_native_quarantine(self, registration, **_kwargs):
            assert registration.project_id == "summitflow"
            return SimpleNamespace(source_id="quarantine", model_dump=lambda **_: receipt(source="quarantine"))
        async def ingest_native_quarantine(self, _source, batch, **_kwargs):
            sent.append(batch.model_dump(mode="json"))
            if len(sent) == 1:
                raise ConnectionError("response lost after durable commit")
            return SimpleNamespace(model_dump=lambda **_: acknowledgement(source="quarantine", disposition="replayed"))
    client = Client()
    assert await delivery_module.deliver(outbox, client, execution_owner_secret="fixture") == 0
    assert outbox.status()["quarantined"] == 1
    reopened = outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0)
    assert await delivery_module.deliver(reopened, client, execution_owner_secret="fixture") == 1
    assert sent[0] == sent[1] and sent[0]["observations"][0]["thread_id"] is None
    assert not reopened.quarantines()


def test_disabled_owner_initializes_and_owns_new_threads_without_capturing(outbox):
    capture = collector(outbox)
    capture.enforce_handshake = True
    capture.initialized = False
    outbox.disable_capture()
    assert capture.client_message({"id": 1, "method": "initialize", "params": {}}) is None
    capture.server_message({"id": 1, "result": {"userAgent": "fixture"}})
    assert capture.client_message({"method": "initialized", "params": {}}) is None
    assert capture.client_message({"id": 2, "method": "thread/start", "params": {}}) is None
    capture.server_message({"id": 2, "result": {"thread": {"id": "new-thread"}}})
    assert "new-thread" in capture.owned and outbox.pending("new-thread") is None
    assert capture.client_message({"id": 3, "method": "thread/resume", "params": {"threadId": "external"}})["error"]
    outbox.enable_capture()
    assert capture.client_message({"id": 4, "method": "thread/read", "params": {"threadId": "new-thread"}}) is None
    assert capture.capturing and outbox.pending("new-thread") is not None


@pytest.fixture(autouse=True)
def isolated_managed_host_settings(tmp_path, monkeypatch):
    """Host policy must never make unit tests initialize the owner's real spools."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    for key in ("SUMMITFLOW_CODEX_MANAGED_CAPTURE", "SUMMITFLOW_CODEX_OUTBOX", "SUMMITFLOW_CODEX_OUTBOXES_JSON", "SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES", "SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS", "SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION"):
        monkeypatch.delenv(key, raising=False)


def test_future_spool_schema_is_rejected_without_mutating_original_pending(outbox):
    outbox.capture("thread", kind="capture_health", payload={"private": "original"})
    original = outbox.pending("thread")
    with outbox.connect() as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema_unsupported"):
        outbox_module.ManagedOutbox(outbox.path, max_bytes=100_000, retention_seconds=0)
    assert outbox.pending("thread") == original
    with outbox.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99
