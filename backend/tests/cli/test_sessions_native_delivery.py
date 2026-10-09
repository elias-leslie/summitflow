"""Native addressing and one-shot reservations must fail without speculative replay."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from cli.commands import sessions_native_delivery as delivery
from cli.lib import native_session_delivery as native

THREAD = "01a10d76-6031-7383-a230-2b721ed5e408"
QUEUE = "01a10d79-0011-7341-9dd5-d79a8fd5f56f"
CLIENT = "761abfd7-aa17-5dc3-a424-d8e6d148b4f9"
TURN = "01a10d79-0011-7341-9dd5-d79a8fd5f56a"
OTHER_TURN = "01a10d79-0011-7341-9dd5-d79a8fd5f56b"


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


@pytest.mark.parametrize("instruction,key", [(" \n", "r1"), ("x" * 2001, "r1"), ("é" * 1001, "r1"), ("Pause", "")])
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


@pytest.fixture
def inspection(monkeypatch):
    private = "private instruction and provider output must not leave inspection"
    replies: dict[str, Any] = {
        "thread/read": {"thread": {"id": THREAD, "preview": private,
                                    "status": {"type": "active", "activeFlags": []}}},
        "thread/queue/list": {"data": [], "nextCursor": None},
        "thread/items/list": {"data": [{"turnId": TURN, "item": {
            "type": "userMessage", "id": "item-fixture", "clientId": CLIENT,
            "content": [{"type": "text", "text": private}],
        }}], "nextCursor": None},
        "thread/turns/list": {"data": [{"id": TURN, "status": "inProgress", "items": [],
                                        "error": {"message": private}}], "nextCursor": None},
    }
    calls = []

    class RPC:
        def __init__(self, root, timeout):
            assert root == "/fixture" and timeout <= 30

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def initialize(self):
            pass

        def call(self, method, params):
            calls.append((method, params))
            assert method in replies, "verification must never submit or mutate"
            response = replies[method]
            if isinstance(response, Exception):
                raise response
            return response(params) if callable(response) else response

    monkeypatch.setattr(native, "NativeRPC", RPC)
    return replies, calls, private


@pytest.mark.parametrize("turn_status,flags,expected", [
    ("inProgress", [], "active"),
    ("inProgress", ["waitingOnApproval"], "waiting_approval"),
    ("inProgress", ["waitingOnUserInput"], "waiting_user_input"),
    ("completed", [], "completed"),
    ("failed", [], "failed"),
    ("interrupted", [], "interrupted"),
])
def test_exact_consumption_and_correlated_execution(inspection, turn_status, flags, expected):
    replies, calls, private = inspection
    replies["thread/turns/list"]["data"][0]["status"] = turn_status
    replies["thread/read"]["thread"]["status"]["activeFlags"] = flags
    result = native.inspect_native_delivery(THREAD, CLIENT, QUEUE, "/fixture")
    assert result["delivery"] == "consumed" and result["observed"] is True
    assert result["turn_id"] == TURN and result["item_id"] == "item-fixture"
    assert result["execution"] == expected
    assert result["generation_fenced"] is False
    assert private not in str(result)
    assert all("input" not in params for _, params in calls)


def test_queue_acceptance_is_not_consumption_and_can_recover_lost_ack(inspection):
    replies, calls, private = inspection
    replies["thread/queue/list"]["data"] = [{"id": QUEUE, "clientUserMessageId": CLIENT,
                                             "input": [{"type": "text", "text": private}]}]
    result = native.inspect_native_delivery(THREAD, CLIENT, None, "/fixture")
    assert result["delivery"] == "queued" and result["queue_id"] == QUEUE
    assert result["observed"] is False and result["execution"] == "not_observed"
    assert "thread/items/list" not in [method for method, _ in calls]
    assert private not in str(result)


def test_deleted_queue_or_unrelated_active_turn_never_proves_consumption(inspection):
    replies, _, _ = inspection
    replies["thread/items/list"]["data"][0]["item"]["clientId"] = "unrelated"
    result = native.inspect_native_delivery(THREAD, CLIENT, QUEUE, "/fixture")
    assert result["delivery"] == "deleted-or-unknown" and result["observed"] is False
    assert result["execution"] == "unknown" and result["thread_state"] == "active"
    assert "turn_id" not in result


def test_unrelated_current_turn_does_not_mark_prior_brief_active(inspection):
    replies, _, _ = inspection
    replies["thread/turns/list"]["data"].insert(0, {"id": OTHER_TURN, "status": "inProgress"})
    result = native.inspect_native_delivery(THREAD, CLIENT, QUEUE, "/fixture")
    assert result["delivery"] == "consumed" and result["observed"] is True
    assert result["execution"] == "unknown"


def test_turn_transition_during_status_read_fails_closed(inspection):
    replies, _, _ = inspection
    original = replies["thread/turns/list"]
    calls = 0

    def turns(params):
        nonlocal calls
        calls += 1
        return original if calls == 1 else {"data": [{"id": OTHER_TURN, "status": "inProgress"}]}

    replies["thread/turns/list"] = turns
    result = native.inspect_native_delivery(THREAD, CLIENT, QUEUE, "/fixture")
    assert result["delivery"] == "consumed" and result["execution"] == "unknown"
    assert result["reason"] == "correlated_turn_changed_during_inspection"


def test_typed_queue_pagination_recovers_exact_client_only(inspection):
    replies, calls, _ = inspection
    replies["thread/queue/list"] = lambda params: (
        {"data": [{"id": QUEUE, "clientUserMessageId": CLIENT, "input": []}], "nextCursor": None}
        if params.get("cursor") == "next-page" else {"data": [], "nextCursor": "next-page"}
    )
    result = native.inspect_native_delivery(THREAD, CLIENT, None, "/fixture")
    assert result["delivery"] == "queued" and result["queue_id"] == QUEUE
    assert calls[-1][1]["cursor"] == "next-page"
    assert "next-page" not in str(result)


@pytest.mark.parametrize("queued", [False, True])
def test_offline_thread_stays_explicit_without_resuming(inspection, queued):
    replies, calls, _ = inspection
    replies["thread/read"]["thread"]["status"] = {"type": "notLoaded"}
    replies["thread/items/list"]["data"] = []
    if queued:
        replies["thread/queue/list"]["data"] = [{"id": QUEUE, "clientUserMessageId": CLIENT, "input": []}]
    result = native.inspect_native_delivery(THREAD, CLIENT, QUEUE, "/fixture")
    assert result["execution"] == "offline_unloaded"
    assert result["delivery"] == ("queued" if queued else "deleted-or-unknown")
    assert result["observed"] is False
    assert all(method != "thread/resume" for method, _ in calls)


@pytest.mark.parametrize("case", ["timeout", "unsupported", "wrong_thread", "queue_mismatch", "duplicate_client", "bad_status"])
def test_inspection_fails_closed(inspection, case):
    replies, _, private = inspection
    if case in {"timeout", "unsupported"}:
        replies["thread/queue/list"] = native.NativeQueueError(
            "native_rpc_timeout" if case == "timeout" else "native_method_unavailable")
    elif case == "wrong_thread":
        replies["thread/read"]["thread"]["id"] = OTHER_TURN
    elif case == "queue_mismatch":
        replies["thread/queue/list"]["data"] = [{"id": QUEUE, "clientUserMessageId": "unrelated", "input": []}]
    elif case == "duplicate_client":
        replies["thread/items/list"]["data"] *= 2
    else:
        replies["thread/read"]["thread"]["status"] = {"type": "futureStatus", "text": private}
    result = native.inspect_native_delivery(THREAD, CLIENT, QUEUE, "/fixture")
    assert result["observed"] is False
    assert result["delivery"] == "unknown" and result["execution"] == "unknown"
    assert private not in str(result)


def test_verify_prior_source_key_is_read_only_and_lost_ack_never_resends(store, monkeypatch):
    queue = MagicMock(side_effect=native.NativeQueueError("native_rpc_timeout"))
    monkeypatch.setattr(delivery, "queue_native_thread", queue)
    receipt = delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")
    inspect = MagicMock(return_value={"delivery": "consumed", "execution": "completed", "observed": True,
                                     "turn_id": TURN, "item_id": "item-fixture", "queue_id": None})
    monkeypatch.setattr(delivery, "inspect_native_delivery", inspect)
    before = list(store)
    result = delivery.verify_native_instruction(THREAD, project="fixture", source_key="revision:1",
                                                 request_id=str(receipt["request_id"]),
                                                 client_id=receipt["client_user_message_id"])
    assert result["execution"] == "completed" and result["resent"] is False
    assert result["request_id"] == receipt["request_id"]
    assert result["client_user_message_id"] == receipt["client_user_message_id"]
    assert store == before
    queue.assert_called_once()
    inspect.assert_called_once_with(THREAD, receipt["client_user_message_id"], None, "/fixture", timeout=5)


@pytest.mark.parametrize("guard", ["request_id", "client_id", "queue_id"])
def test_verify_exact_receipt_guards_reject_without_native_read(store, monkeypatch, guard):
    def queue(thread, instruction, client, root):
        return {"thread_id": thread, "queue_id": QUEUE, "client_user_message_id": client}

    monkeypatch.setattr(delivery, "queue_native_thread", queue)
    delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")
    inspect = MagicMock()
    monkeypatch.setattr(delivery, "inspect_native_delivery", inspect)
    with pytest.raises(ValueError, match="identity"):
        guards: dict[str, Any] = {guard: "incorrect"}
        delivery.verify_native_instruction(THREAD, project="fixture", source_key="revision:1",
                                            **guards)
    inspect.assert_not_called()


def test_retained_failed_send_needs_no_native_read(store, monkeypatch):
    monkeypatch.setattr(delivery, "queue_native_thread", MagicMock(side_effect=native.NativeQueueError(
        "native_server_unavailable", uncertain=False)))
    delivery.send_native_instruction(THREAD, "Pause", project="fixture", source_key="revision:1")
    inspect = MagicMock()
    monkeypatch.setattr(delivery, "inspect_native_delivery", inspect)
    result = delivery.verify_native_instruction(THREAD, project="fixture", source_key="revision:1")
    assert result["delivery"] == "failed" and result["observed"] is False and result["resent"] is False
    inspect.assert_not_called()


def test_cli_verify_routes_exact_receipt_and_unknown_timeout(monkeypatch):
    from cli.commands import sessions_fleet
    from cli.main import app

    verify = MagicMock(return_value={"delivery": "unknown", "reason": "native_rpc_timeout", "resent": False})
    monkeypatch.setattr(delivery, "verify_native_instruction", verify)
    monkeypatch.setattr(sessions_fleet, "get_config", lambda: SimpleNamespace(project_id="fixture"))
    result = CliRunner().invoke(app, ["sessions", "verify", THREAD, "--source-key", "revision:1", "--timeout", "0.5"])
    assert result.exit_code == 0 and "native_rpc_timeout" in result.output
    verify.assert_called_once_with(THREAD, project="fixture", source_key="revision:1",
                                  request_id=None, queue_id=None, client_id=None, timeout=.5)


@pytest.mark.parametrize("case,expected", [("timeout", "native_rpc_timeout"),
                                          ("error", "native_read_rejected"),
                                          ("unsupported", "native_method_unavailable")])
def test_real_rpc_verification_timeout_or_private_provider_error_never_leaks(tmp_path, monkeypatch, case, expected):
    server = tmp_path / "codex"
    server.write_text(f"#!{sys.executable}\n" + f"""import sys,json,time
for line in sys.stdin:
 w=json.loads(line)
 if w.get('method')=='initialize': print(json.dumps({{'id':w['id'],'result':{{}}}}),flush=True)
 if w.get('method')=='thread/read':
  if {case!r}=='timeout': time.sleep(100)
  print(json.dumps({{'id':w['id'],'error':{{'code':-32601 if {case!r}=='unsupported' else -1,'message':'private provider response'}}}}),flush=True)
 if w.get('method') not in {{'initialize','initialized','thread/read'}}: raise Exception('unexpected mutation')
""")
    server.chmod(0o700)
    monkeypatch.setattr(native, "transcript_library", lambda: None)
    monkeypatch.setattr(native, "import_module", lambda _name: SimpleNamespace(codex_binary=lambda: str(server)))
    result = native.inspect_native_delivery(THREAD, CLIENT, QUEUE, str(tmp_path), timeout=.1)
    assert result["delivery"] == "unknown" and result["reason"] == expected
    assert result["observed"] is False
    assert "private" not in str(result)
