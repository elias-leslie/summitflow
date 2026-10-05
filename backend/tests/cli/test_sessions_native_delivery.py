"""Native addressing and one-shot reservations must fail without speculative replay."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from cli.commands import sessions_native_delivery as delivery
from cli.lib import native_session_delivery as native

THREAD = "01a10d76-6031-7383-a230-2b721ed5e408"
QUEUE = "01a10d79-0011-7341-9dd5-d79a8fd5f56f"


@pytest.fixture
def store(monkeypatch):
    records = []
    monkeypatch.setattr(delivery, "get_project_root_path", lambda _project: "/fixture")
    monkeypatch.setattr(delivery, "verify_thread_binding", lambda *args: {"thread_id": THREAD, "project_id": "fixture", "binding_fingerprint": "pinned"})

    def append(project, trace, *, source_key, event_type, attributes, return_created=False):
        existing = next((x for x in records if x["source_key"] == source_key), None)
        if existing:
            if existing["attributes"] != attributes:
                raise ValueError("Source key already retained with different content")
            return {**existing, "created": False}
        record = {"id": len(records) + 1, "source_key": source_key, "event_type": event_type, "attributes": attributes}
        records.append(record)
        return {**record, "created": True}

    monkeypatch.setattr(delivery, "append_fleet_event", append)
    monkeypatch.setattr(delivery, "read_fleet_page", lambda *args, **kwargs: records)
    return records


def test_queued_receipt_and_retry_dispatch_once(store, monkeypatch):
    queue = MagicMock(return_value={"thread_id": THREAD, "queue_id": QUEUE, "client_user_message_id": "correlated"})
    monkeypatch.setattr(delivery, "queue_native_thread", queue)
    first = delivery.send_native_instruction(THREAD, "Pause password=private", project="fixture", source_key="revision:1")
    retry = delivery.send_native_instruction(THREAD, "Pause password=private", project="fixture", source_key="revision:1")
    assert first == retry
    assert first["delivery"] == "queued" and first["observed"] is False
    assert queue.call_args.args[1] == "Pause [REDACTED]"
    queue.assert_called_once()
    assert "instruction" not in store[0]["attributes"]
    monkeypatch.setattr(delivery, "verify_thread_binding", lambda *args: {"thread_id": THREAD, "project_id": "fixture", "binding_fingerprint": "new explicit binding, same project"})
    assert delivery.send_native_instruction(THREAD, "Pause password=private", project="fixture", source_key="revision:1") == first
    with pytest.raises(ValueError, match="different content"):
        delivery.send_native_instruction(THREAD, "Changed", project="fixture", source_key="revision:1")
    queue.assert_called_once()


@pytest.mark.parametrize("uncertain,expected", [(True, "uncertain"), (False, "failed")])
def test_native_failure_and_retry_never_replay(store, monkeypatch, uncertain, expected):
    queue = MagicMock(side_effect=native.NativeQueueError("native_rpc_closed", uncertain=uncertain))
    monkeypatch.setattr(delivery, "queue_native_thread", queue)
    first = delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")
    assert first["delivery"] == expected
    assert delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1") == first
    queue.assert_called_once()


def test_crash_after_reservation_does_not_replay(store, monkeypatch):
    queue = MagicMock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(delivery, "queue_native_thread", queue)
    with pytest.raises(KeyboardInterrupt):
        delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")
    result = delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")
    assert result["delivery"] == "pending-or-uncertain"
    queue.assert_called_once()


def test_receipt_write_failure_leaves_reservation_without_replay(store, monkeypatch):
    queue = MagicMock(return_value={"thread_id": THREAD, "queue_id": QUEUE, "client_user_message_id": "correlated"})
    monkeypatch.setattr(delivery, "queue_native_thread", queue)
    append = delivery.append_fleet_event

    def fail_result(*args, **kwargs):
        if kwargs["source_key"] == "result":
            raise OSError("receipt storage unavailable")
        return append(*args, **kwargs)

    monkeypatch.setattr(delivery, "append_fleet_event", fail_result)
    with pytest.raises(OSError):
        delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")
    assert delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")["delivery"] == "pending-or-uncertain"
    queue.assert_called_once()


@pytest.mark.parametrize("instruction,key", [(" \n", "r1"), ("x" * 2001, "r1"), ("Pause", "")])
def test_invalid_instruction_or_key_never_reserves(store, instruction, key):
    with pytest.raises(ValueError):
        delivery.send_native_instruction(THREAD, instruction, project="fixture", source_key=key)
    assert not store


@pytest.fixture
def identity(tmp_path, monkeypatch):
    path = tmp_path / f"rollout-{THREAD}.jsonl"
    path.touch()
    binding = SimpleNamespace(project_id="fixture", project_root=str(tmp_path), parent_session_id=None, fingerprint="pinned")
    info = SimpleNamespace(session_id=THREAD, cwd=tmp_path, identity_error=None, ownership_ambiguous=False, parent_session_id=None, agent_path=None)
    library = SimpleNamespace(TRANSCRIPTS_ROOT=tmp_path, read_transcript_info=lambda *args, **kwargs: info, discover_open_transcripts=lambda: None)
    runner = SimpleNamespace(_resolve_project_context=lambda *args: ({"project_id": "fixture", "repo_root": str(tmp_path)}, tmp_path, "", True), _project_mapping_state=lambda *args, **kwargs: ("matched", ""))
    modules = {"codex_sync_bindings": SimpleNamespace(load_snapshot=lambda: {THREAD: binding}), "codex_sync_runner": runner}
    monkeypatch.setattr(native, "transcript_library", lambda: library)
    monkeypatch.setattr(native, "import_module", lambda name: modules[name])
    return tmp_path, binding, info, modules, runner


def test_bound_and_canonical_unbound_offline_threads(identity):
    root, _, _, modules, _ = identity
    assert native.verify_thread_binding(THREAD, "fixture", str(root))["binding_fingerprint"] == "pinned"
    modules["codex_sync_bindings"].load_snapshot = lambda: {}
    assert native.verify_thread_binding(THREAD, "fixture", str(root))["project_id"] == "fixture"


@pytest.mark.parametrize("case", ["foreign", "subagent", "ambiguous", "unknown", "owner_mismatch", "wrong_project"])
def test_identity_rejections(identity, case):
    root, binding, info, _modules, runner = identity
    if case == "foreign":
        binding.project_id = "foreign"
    if case == "subagent":
        info.parent_session_id = "parent"
    if case == "ambiguous":
        info.ownership_ambiguous = True
    if case == "unknown":
        info.session_id = "other"
    if case == "owner_mismatch":
        runner._project_mapping_state = lambda *args, **kwargs: ("mismatch", "")
    if case == "wrong_project":
        runner._resolve_project_context = lambda *args: (None, root, "", False)
    with pytest.raises(ValueError):
        native.verify_thread_binding(THREAD, "fixture", str(root))


@pytest.mark.parametrize("thread", ["root-abc", THREAD.upper(), "../thread", ""])
def test_exact_uuid_required(thread):
    with pytest.raises(ValueError):
        native.exact_uuid(thread)


@pytest.mark.parametrize("case", ["success", "mismatch", "error", "closed", "oversized", "malformed", "stalled", "flood"])
def test_typed_native_transport(tmp_path, monkeypatch, case):
    server = tmp_path / "codex"
    server.write_text(f"#!{sys.executable}\n" + f"""import sys,json,time
for line in sys.stdin:
 w=json.loads(line)
 if w.get('method')=='initialize': print(json.dumps({{'id':1,'result':{{}}}}),flush=True)
 if w.get('method')=='thread/queue/add':
  if {case!r}=='closed': sys.exit(0)
  if {case!r}=='oversized': sys.stdout.write('x'*20000);sys.stdout.flush();time.sleep(100)
  if {case!r}=='malformed': print('not json',flush=True);time.sleep(100)
  if {case!r}=='stalled': time.sleep(100)
  if {case!r}=='flood':
   while True: print(json.dumps({{'method':'notification','params':{{}}}}),flush=True)
  p=w['params']; q={{'id':{QUEUE!r},'input':p['input'],'clientUserMessageId':p['clientUserMessageId']}}
  if {case!r}=='mismatch': q['clientUserMessageId']='wrong'
  r={{'id':2,'result':{{'queuedSubmission':q}}}}
  if {case!r}=='error': r={{'id':2,'error':{{'code':-1,'message':'private provider error must not escape'}}}}
  print(json.dumps(r),flush=True)
""")
    server.chmod(0o700)
    monkeypatch.setattr(native, "transcript_library", lambda: None)
    monkeypatch.setattr(native, "import_module", lambda _name: SimpleNamespace(codex_binary=lambda: str(server)))
    monkeypatch.setattr(native, "RPC_TIMEOUT_SECONDS", 0.3 if case in {"stalled", "flood"} else 5)
    if case == "success":
        assert native.queue_native_thread(THREAD, "Pause", "client-id", str(tmp_path)) == {"thread_id": THREAD, "queue_id": QUEUE, "client_user_message_id": "client-id"}
    else:
        with pytest.raises(native.NativeQueueError) as error:
            native.queue_native_thread(THREAD, "Pause", "client-id", str(tmp_path))
        assert error.value.uncertain
        assert "private" not in str(error.value)


def test_cli_native_requires_key_and_fleet_default_preserved(monkeypatch):
    from cli.commands import sessions_fleet
    from cli.main import app

    call = MagicMock(return_value={"delivery": "available-via-wait"})
    monkeypatch.setattr(sessions_fleet, "_call", call)
    result = CliRunner().invoke(app, ["sessions", "send", "root-existing", "Pause"])
    assert result.exit_code == 0
    call.assert_called_once()
    result = CliRunner().invoke(app, ["sessions", "send", THREAD, "Pause", "--delivery", "native-thread"])
    assert result.exit_code != 0 and "--source-key" in result.output
