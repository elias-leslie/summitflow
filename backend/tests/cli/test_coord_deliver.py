"""Coordination inbox wakes through Tether's gated delivery queue (Agent waits P2, SummitFlow side)."""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli.lib import (
    coord,
    coord_deliver,
    coord_lineage,
    coord_remote,
    coord_wake,
    coordinators,
    leases,
)
from cli.main import app

runner = CliRunner()
COORD_INBOX = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "coord_inbox.py"
WIDGET = "ab12cd34"
OTHER = "cd56ef78"
# Live harness processes and the window each runs in; the default identity anchor is the first.
ANCHORS = {"4242:99": WIDGET, "5151:1": OTHER}
SENDER_ANCHOR = "5151:1"


def _as(monkeypatch, harness: str, sid: str) -> None:
    for name in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID" if harness == "claude" else "CODEX_THREAD_ID", sid)


def _identity(agent_id: str, session: str, anchor: str = "4242:99", last: str = "2026-10-31",
              main: bool | None = None) -> None:
    with leases._lock("_coord"):
        doc = coord_lineage.load_doc()
        row: dict[str, Any] = {"anchor": anchor, "session": session, "last": last}
        if main is not None:
            row["main"] = main
        doc.setdefault("identities", {})[agent_id] = row
        coord_lineage.save_doc(doc)


def _line(to: str, **kw: Any) -> str | None:
    who = coord_deliver.target(to)
    assert who is not None
    return coord_deliver.summary(who, **kw)


class FakeTether:
    """Tether's deliveries routes as SummitFlow sees them."""

    def __init__(self, version: int = 16) -> None:
        self.version = version
        self.calls: list[tuple[str, str, Any]] = []
        self.answer: tuple[int, Any] | None = None
        self.records: dict[str, dict[str, Any]] = {}
        self.nested: set[str] = set()
        self.on_post: Any = None

    def __call__(self, method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> tuple[int, Any]:
        self.calls.append((method, path, body))
        body = body or {}
        if path.endswith("/deliveries") and method == "POST":
            if self.on_post is not None:
                self.on_post(body)
            if self.answer is not None:
                return self.answer
            record = {"id": f"{len(self.records):012x}", "sessionId": path.split("/")[3], "source": body["source"],
                      "state": "queued", "queuedAt": 1, "deliveredAt": None, "via": None, "coalesced": False}
            self.records[record["id"]] = record
            return 201, record
        if path.startswith("/v1/deliveries/"):
            record = self.records.get(path.rsplit("/", 1)[1])
            return (200, record) if record else (404, {"error": "not_found"})
        if path == "/v1/waits/check":
            return 200, {"kind": body["kind"], "ref": body["ref"], "armed": 0}
        return 404, {"error": "not_found"}

    def posts(self) -> list[tuple[str, dict[str, Any]]]:
        return [(path, body) for method, path, body in self.calls if method == "POST" and path.endswith("/deliveries")]

    def nudges(self) -> list[dict[str, Any]]:
        return [body for _, path, body in self.calls if path == "/v1/waits/check"]


@pytest.fixture
def tether(monkeypatch) -> FakeTether:
    from app.services import tether as service

    fake = FakeTether()
    monkeypatch.setattr(service, "request", fake)
    monkeypatch.setattr(coord_deliver, "api_version", lambda: fake.version)
    monkeypatch.setattr(coordinators, "widget_for_anchor", lambda anchor: ANCHORS.get(anchor or ""))
    monkeypatch.setattr(coord_lineage, "anchor_alive", lambda anchor: anchor in ANCHORS)
    monkeypatch.setattr(coord_deliver, "_nested", lambda anchor: anchor in fake.nested)
    monkeypatch.setattr(coord_deliver, "_window_anchors", lambda w: [a for a, wid in ANCHORS.items() if wid == w])
    monkeypatch.setattr(coord_wake, "STATE", Path(coord_lineage._doc_path()).parent / "inbox-state")
    return fake


# ---------------------------------------------------------------- the line


def test_line_counts_requests_and_names_senders_without_text(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    for sid in ("aaaaaa-1", "bbbbbb-1", "cccccc-1", "dddddd-1"):
        _as(monkeypatch, "claude", sid)
        coord.send("codex:target", f"secret plan from {sid}")
    line = _line("codex:target")
    assert line == "[Message] 4 requests from cc:aaaaaa, cc:bbbbbb, cc:cccccc +1 · st sessions inbox"
    assert "secret" not in line


def test_line_reports_unseen_acks_and_memory(monkeypatch, tether):
    _identity("cc:sender", "sender-session", anchor=SENDER_ANCHOR)
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("cc:sender", "", "sender-session", "claude_code"))
    sent = coord.send("codex:target", "may I rebuild?")
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("codex:target", "", "target-thread", "codex"))
    row = coord.ack(sent["id"], "no", "busy deploying")
    assert _line("cc:sender", memory=True) == (
        "[Message] 1 ack from codex:target · a memory notice for this pane · st sessions inbox")
    coord_wake.mark_woke("cc:sender", [])  # woke state does not hide content; seen state does
    coord_wake.STATE.mkdir(parents=True, exist_ok=True)
    coord_wake.seen_path("cc:sender").write_text(json.dumps({f"{row['id']}:ack:{row['acked_at']}": time.time()}))
    assert _line("cc:sender") is None


def test_ids_that_are_not_agent_ids_are_never_put_on_the_line(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    coord.send("codex:target", "x", sender="cc:ok/../rm -rf")
    assert _line("codex:target") == "[Message] 1 request from another agent · st sessions inbox"


def test_long_ids_name_fewer_senders_to_stay_within_tethers_line_limit(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    monkeypatch.setattr(coord_deliver, "LINE_MAX", 160)
    for n in range(4):
        coord.send("codex:target", "x", sender=f"codex:{n}{'a' * 63}@agent-host-with-a-long-name")
    assert _line("codex:target") == (
        f"[Message] 4 requests from codex:0{'a' * 63}@agent-host-with-a-long-name +3 · st sessions inbox")
    monkeypatch.setattr(coord_deliver, "LINE_MAX", 80)
    assert _line("codex:target") == "[Message] 4 requests from 4 agents · st sessions inbox"


# ---------------------------------------------------------------- wake


def test_wake_queues_one_line_on_the_recipients_window_and_records_woke(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    _as(monkeypatch, "claude", "sender-01")
    row = coord.send("codex:target", "rebuild ok?")
    queued = coord_deliver.wake("codex:target", [f"{row['id']}:req"])
    assert queued and queued["widget"] == WIDGET
    [(path, body)] = tether.posts()
    assert path == f"/v1/sessions/{WIDGET}/deliveries"
    assert body == {"source": "coord:codex:target", "line": "[Message] 1 request from cc:sender · st sessions inbox"}
    assert f"{row['id']}:req" in coord_wake.load_woke("codex:target")


def test_a_session_prefix_address_wakes_the_identity_it_names(monkeypatch, tether):
    _identity("cc:c9ffbd", "c9ffbd05-c536-446f-82f7-30690775f33e")
    _as(monkeypatch, "claude", "sender-02")
    coord.send("c9ffbd05-c536-4", "hello")
    assert coord_deliver.wake("c9ffbd05-c536-4", ["x:req"])
    assert tether.posts()[0][1]["source"] == "coord:cc:c9ffbd"
    assert "x:req" in coord_wake.load_woke("cc:c9ffbd")


@pytest.mark.parametrize("case", ["old_tether", "no_window", "agy", "remote", "refused", "gone", "nested"])
def test_unresolved_recipients_keep_todays_path(monkeypatch, tether, case):
    target = {"agy": "agy:abc123", "remote": "a810c7e0@agent-work"}.get(case, "codex:target")
    _identity(target, "019a-target", anchor="1:1" if case == "no_window" else "4242:99")
    coord.send(target, "hello", sender="cc:sender")
    if case == "old_tether":
        tether.version = 15
    if case == "refused":
        tether.answer = (409, {"error": "delivery_unsupported"})
    if case == "gone":
        tether.answer = (404, {"error": "not_found"})
    if case == "nested":
        tether.nested.add("4242:99")  # a headless harness an agent runs inherits its window
    assert coord_deliver.wake(target, ["k:req"]) is None
    assert coord_wake.load_woke(target.split("@")[0]) == {}
    if case not in ("refused", "gone"):
        assert tether.posts() == []


@pytest.mark.parametrize("answer", ["unreachable", "server_error"])
def test_no_answer_from_tether_is_unsettled_and_records_nothing(monkeypatch, tether, answer):
    from app.services import tether as service

    _identity("codex:target", "019a-target")
    coord.send("codex:target", "hello", sender="cc:sender")
    if answer == "unreachable":
        monkeypatch.setattr(service, "request", lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError()))
    else:
        tether.answer = (500, {"error": "internal"})
    with pytest.raises(coord_deliver.Unsettled):
        coord_deliver.wake("codex:target", ["k:req"])
    assert coord_wake.load_woke("codex:target") == {}
    assert coord_deliver.safe_wake("codex:target", ["k:req"]) is None


def test_woke_is_recorded_before_the_post(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    coord.send("codex:target", "hello", sender="cc:sender")
    during: list[bool] = []
    tether.on_post = lambda _body: during.append("k:req" in coord_wake.load_woke("codex:target"))
    assert coord_deliver.wake("codex:target", ["k:req"])
    assert during == [True]  # the recipient's watcher, looking meanwhile, does not queue a second line


def test_a_codex_child_thread_keeps_its_own_path(monkeypatch, tether):
    _identity("codex:parent", "019a-parent", main=True)
    _identity("codex:child", "019a-child", last="2026-10-31T12")
    coord.send("codex:child", "hello", sender="cc:sender")
    assert coord_deliver.target("codex:child") is None
    assert coord_deliver.wake("codex:child", ["k:req"]) is None and tether.posts() == []
    assert coord_deliver.target("codex:parent") is not None


def test_a_predecessor_address_wakes_the_windows_current_agent_with_its_family_counted(monkeypatch, tether):
    _identity("cc:before", "before-clear", last="2026-10-31T10", main=True)
    _identity("cc:after", "after-clear", last="2026-10-31T11", main=True)
    coord.send("cc:before", "asked before the reset", sender="cc:sender")
    coord.send("cc:after", "asked after", sender="cc:sender2")
    queued = coord_deliver.wake("cc:before", ["k:req"])
    assert queued and queued["agent_id"] == "cc:after"
    [(_, body)] = tether.posts()
    assert body == {"source": "coord:cc:after",
                    "line": "[Message] 2 requests from cc:sender, cc:sender2 · st sessions inbox"}
    assert "k:req" in coord_wake.load_woke("cc:after")


def test_an_identity_on_a_process_that_is_no_longer_the_windows_newest_keeps_its_path(monkeypatch, tether):
    monkeypatch.setitem(ANCHORS, "6161:1", WIDGET)  # a background job of the window's agent
    _identity("cc:pane", "pane-session", last="2026-10-31T10")
    _identity("cc:job", "job-session", anchor="6161:1", last="2026-10-31T11")
    coord.send("cc:pane", "hello", sender="cc:sender")
    assert coord_deliver.target("cc:pane") is None
    assert coord_deliver.target("cc:job") is not None


def test_send_and_ack_queue_lines_for_each_side_and_nudge_reply_waits(monkeypatch, tether):
    tether.version = 17
    _identity("cc:sender", "sender-03", anchor=SENDER_ANCHOR)
    _identity("codex:target", "target-03")
    _as(monkeypatch, "claude", "sender-03")
    monkeypatch.setattr("cli.commands.sessions_fleet._send_across_machines", lambda *a, **k: False)
    sent = runner.invoke(app, ["sessions", "send", "codex:target", "may I rebuild?"])
    assert sent.exit_code == 0, sent.output
    [row] = coord._load_ledger()
    assert f"Tether delivers a [Message] line to its window {WIDGET}" in sent.output
    _as(monkeypatch, "codex", "target-03")
    acked = runner.invoke(app, ["sessions", "ack", row["id"], "yes"])
    assert acked.exit_code == 0, acked.output
    assert "Tether delivers a [Message] line about the ack to cc:sender" in acked.output
    assert [(path.split("/")[3], body["source"]) for path, body in tether.posts()] == [
        (WIDGET, "coord:codex:target"), (OTHER, "coord:cc:sender")]
    assert tether.posts()[1][1]["line"] == "[Message] 1 ack from codex:target · st sessions inbox"
    assert tether.nudges() == [{"kind": "reply", "ref": row["id"]}]


def test_no_reply_nudge_before_tether_api_17(monkeypatch, tether):
    coord_deliver.nudge("reply", "abc123")
    assert tether.nudges() == []
    tether.version = 17
    coord_deliver.nudge("job", "f" * 32)
    assert tether.nudges() == [{"kind": "job", "ref": "f" * 32}]


def test_a_failing_tether_never_fails_the_send(monkeypatch, tether):
    monkeypatch.setattr(coord_deliver, "wake", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _as(monkeypatch, "claude", "sender-04")
    monkeypatch.setattr("cli.commands.sessions_fleet._send_across_machines", lambda *a, **k: False)
    result = runner.invoke(app, ["sessions", "send", "codex:target", "hello"])
    assert result.exit_code == 0 and "the recipient's hook shows it" in result.output


# ---------------------------------------------------------------- the recipient's own watcher


@pytest.fixture
def inbox(monkeypatch, tether):
    spec = importlib.util.spec_from_file_location("coord_inbox_p2", COORD_INBOX)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.argv", [str(COORD_INBOX), str(COORD_INBOX.parents[2] / "backend")])
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "STATE", coord_wake.STATE)
    monkeypatch.setattr(module, "POLL", 0.01)
    monkeypatch.setattr(module, "WATCH_SECONDS", 0.15)
    monkeypatch.setattr(module, "memory", lambda *_a, **_k: None)
    monkeypatch.setattr(coord_wake, "type_line", lambda *_a: pytest.fail("nothing types into a pane"))
    monkeypatch.setenv("TMUX", "/sock,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    return module


@pytest.mark.parametrize("provider", ["claude_code", "codex"])
def test_watcher_queues_through_tether_and_keeps_watching(monkeypatch, inbox, tether, capsys, provider):
    _identity("codex:target", "target-05")
    req = ("cd34:req", "REQUEST cd34 from cc:x: may I rebuild?", False)
    coord.send("codex:target", "may I rebuild?", sender="cc:x")
    monkeypatch.setattr(inbox, "pending", lambda: ("codex:target", [req]))
    assert inbox.watch(provider) == 0  # no asyncRewake exit, no typing: it ran to its deadline
    assert capsys.readouterr().err == ""
    assert len(tether.posts()) == 1  # queued once, not every poll
    assert "cd34:req" in coord_wake.load_woke("codex:target")
    assert "cd34:req" not in coord_wake.load_seen("codex:target")  # the turn hook still shows it


def test_watcher_skips_an_item_the_sender_woke_and_reminds_after_remind(monkeypatch, inbox, tether, capsys):
    _identity("codex:target", "target-06")
    coord.send("codex:target", "may I rebuild?", sender="cc:x")
    req = ("ef56:req", "REQUEST ef56 from cc:x", False)
    monkeypatch.setattr(inbox, "pending", lambda: ("codex:target", [req]))
    coord_wake.mark_woke("codex:target", ["ef56:req"])
    assert inbox.watch("claude_code") == 0 and tether.posts() == []
    coord_wake.mark_woke("codex:target", ["ef56:req"], now=time.time() - inbox.REMIND - 1)
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 1


def test_watcher_falls_back_to_the_asyncrewake_wake_without_tether(monkeypatch, inbox, tether, capsys):
    tether.version = 15
    req = ("cd34:req", "REQUEST cd34 from cc:x: may I rebuild?", False)
    monkeypatch.setattr(inbox, "pending", lambda: ("cc:receiver", [req]))
    assert inbox.watch("claude_code") == 2
    assert "REQUEST cd34" in capsys.readouterr().err


def test_watcher_announces_a_memory_notice_once_and_leaves_it_for_the_turn_hook(monkeypatch, inbox, tether):
    _identity("codex:target", "target-07")
    done: list[bool] = []

    class Notice:
        text = "Memory notice: a process in this pane was killed"

        def done(self, delivered: bool = True) -> None:
            done.append(delivered)

    monkeypatch.setattr(inbox, "memory", lambda *_a, **_k: Notice())
    monkeypatch.setattr(inbox, "MEM_RECHECK", 0.0)
    monkeypatch.setattr(inbox, "pending", lambda: ("codex:target", []))
    assert inbox.watch("codex") == 0
    [(_, body)] = tether.posts()
    assert body["line"] == "[Message] a memory notice for this pane · st sessions inbox"
    assert done and not any(done)  # never recorded as shown: the turn hook shows it in full


def test_watcher_never_types_while_tether_does_not_answer_and_retries(monkeypatch, inbox, tether, capsys):
    _identity("codex:target", "target-10")
    coord.send("codex:target", "may I rebuild?", sender="cc:x")
    tether.answer = (500, {"error": "internal"})
    monkeypatch.setattr(inbox, "RETRY", 0.0)
    monkeypatch.setattr(inbox, "pending", lambda: ("codex:target", [("ab01:req", "REQUEST ab01", False)]))
    assert inbox.watch("codex") == 0 and capsys.readouterr().err == ""  # type_line would fail the test
    assert len(tether.posts()) > 1  # tried again
    assert coord_wake.load_woke("codex:target") == {}


def test_a_watcher_left_from_before_a_context_reset_exits(monkeypatch, inbox, tether):
    _identity("cc:before", "before-clear", last="2026-10-31T10", main=True)
    _identity("cc:after", "after-clear", last="2026-10-31T11", main=True)
    coord.send("cc:before", "hi", sender="cc:x")
    monkeypatch.setattr(inbox, "WATCH_SECONDS", 30)
    monkeypatch.setattr(inbox, "pending", lambda: ("cc:before", [("ab02:req", "REQUEST ab02", False)]))
    assert inbox.watch("claude_code") == 0 and tether.posts() == []  # cc:after's own watcher wakes it


def test_pi_idle_check_skips_items_a_tether_line_wakes_it_for(monkeypatch, inbox, tether, capsys):
    req = ("aa11:req", "REQUEST aa11 from cc:x: hi", False)
    monkeypatch.setattr(inbox, "pending", lambda: ("pi:target", [req]))
    monkeypatch.setattr(inbox.coord, "adopt_hook_identity", lambda payload: None)
    monkeypatch.setattr(inbox.coord_lineage, "observe", lambda **_: [])
    monkeypatch.setattr("sys.argv", [str(COORD_INBOX), "backend", "turn", "pi"])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"hook_event_name": "PiIdle"})))
    coord_wake.mark_woke("pi:target", ["aa11:req"])
    assert inbox.main() == 0 and capsys.readouterr().out == ""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"hook_event_name": "PostToolUse"})))
    assert inbox.main() == 0 and "REQUEST aa11" in capsys.readouterr().out  # its turn hook still shows it


# ---------------------------------------------------------------- across machines


REMOTE = {"id": "a810c7e0", "host": "agent-work", "generation": "g" * 64, "rootRequestId": "rh2b-live-1",
          "displayTitle": "Aico", "tmux": {"sessionName": "aico-a810c7e0"}}


@pytest.fixture
def hub(monkeypatch, tether):
    from app.services import tether as service

    monkeypatch.delenv("ST_AGENT_HOST", raising=False)
    monkeypatch.setenv("AICO_WIDGET_ID", "ea3f2738")
    monkeypatch.setattr(coord_remote.leases, "identify_agent", lambda **_: ("cc:ea3f27", "", "", ""))
    monkeypatch.setattr(service, "request_all", lambda path: [(200, {"items": [REMOTE]})])
    return tether


def test_a_host_window_gets_a_gated_line_through_the_hub_not_a_paste(monkeypatch, hub):
    result = runner.invoke(app, ["sessions", "send", "a810c7e0", "Run the check"])
    assert result.exit_code == 0, result.output
    [row] = coord._load_ledger()
    [(path, body)] = hub.posts()
    assert path == "/v1/sessions/a810c7e0/deliveries"
    assert body == {"source": "coord:a810c7e0@agent-work",
                    "line": "[Message] 1 request from cc:ea3f27 · st sessions inbox"}
    assert not [c for c in hub.calls if c[1].endswith("/inject")]
    assert row["to"] == "a810c7e0@agent-work"


def test_a_host_tether_without_deliveries_still_gets_the_inject(monkeypatch, hub):
    hub.answer = (404, {"error": "not_found"})
    original = hub.__call__

    def route(method, path, body=None, **kw):
        if path.endswith("/inject"):
            hub.calls.append((method, path, body))
            return 200, {"delivered": True}
        return original(method, path, body, **kw)

    from app.services import tether as service

    monkeypatch.setattr(service, "request", route)
    result = runner.invoke(app, ["sessions", "send", "a810c7e0", "Run the check"])
    assert result.exit_code == 0, result.output
    assert [c[1] for c in hub.calls if c[0] == "POST"] == ["/v1/sessions/a810c7e0/deliveries",
                                                          "/v1/sessions/a810c7e0/inject"]


def test_an_ack_for_a_host_agent_goes_to_its_window_as_a_line(monkeypatch, hub):
    row = coord.send("cc:4a9a07", "may I?", sender="cc:hostagent@agent-work",
                     remote={"host": "agent-work", "reply_window": "a810c7e0"})
    monkeypatch.setattr(coord_remote.leases, "identify_agent", lambda **_: ("cc:4a9a07", "", "ws-session", ""))
    window = coord_remote.post_ack(coord.ack(row["id"], "yes"))
    assert window and window["id"] == "a810c7e0"
    [(path, body)] = hub.posts()
    assert path == "/v1/sessions/a810c7e0/deliveries"
    assert body == {"source": "coord:a810c7e0@agent-work",  # one source per host window: requests and acks
                    "line": "[Message] 1 ack from cc:4a9a07 · st sessions inbox"}


def test_a_hub_that_does_not_answer_never_leads_to_a_paste(monkeypatch, hub):
    hub.answer = (502, {"error": "upstream"})
    result = runner.invoke(app, ["sessions", "send", "a810c7e0", "Run the check"])
    assert result.exit_code == 0, result.output
    assert not [c for c in hub.calls if c[1].endswith("/inject")]
    assert [row["to"] for row in coord._load_ledger()] == ["a810c7e0@agent-work"]  # recorded; its inbox lists it


def test_a_host_agents_request_and_ack_wake_the_workstation_agent(monkeypatch, hub):
    hub.version = 17
    _identity("cc:4a9a07", "ws-session")
    row = coord_remote.record_from_host("cc:4a9a07", "can I deploy?", sender="cc:hostagent", host="agent-work",
                                        reply_to="a810c7e0")
    assert hub.posts()[0][1]["source"] == "coord:cc:4a9a07"
    assert f"{row['id']}:req" in coord_wake.load_woke("cc:4a9a07")
    # And the other way: the workstation agent asked, the host agent acks.
    asked = coord.send("a810c7e0@agent-work", "check please", sender="cc:4a9a07")
    coord_remote.ack_from_host(asked["id"], "yes", None, sender="cc:hostagent", host="agent-work", window="a810c7e0")
    assert hub.posts()[-1][1] == {"source": "coord:cc:4a9a07", "line": (
        "[Message] 1 request from cc:hostagent@agent-work · 1 ack from cc:hostagent@agent-work · st sessions inbox")}
    assert hub.nudges() == [{"kind": "reply", "ref": asked["id"]}]


# ---------------------------------------------------------------- native-thread sends and service jobs


def test_native_thread_send_reports_tethers_delivery_state_without_waiting(monkeypatch, tether):
    from cli.commands import sessions_native_delivery as delivery
    from cli.lib import coord_route

    _identity("codex:target", "thread-08")
    _as(monkeypatch, "claude", "native-sender-08")
    monkeypatch.setattr(coord_route, "live_agent_for_session", lambda _thread: "codex:target")
    monkeypatch.setattr(coord_wake, "codex_watch_pid", lambda _a: pytest.fail("no guessing from the watcher"))
    monkeypatch.setattr(delivery.coord_wake, "wait_surfaced", lambda *a: pytest.fail("never waits"))
    out = delivery._deliver_live("thread", "Pause the lane", project="fixture", source_key="k8")
    assert out is not None
    assert (out["delivery"], out["observed"], out["wake"]["state"]) == ("queued", False, "queued")
    assert "idle and nobody is typing" in out["reason"]
    tether.records[out["tether_delivery_id"]].update(state="dropped")
    monkeypatch.setattr(coord_deliver, "state", lambda did: {**tether.records[did], "state": "dropped"})
    out = delivery._deliver_live("thread", "Second instruction", project="fixture", source_key="k9")
    assert out is not None and out["delivery"] == "queued" and "did not deliver" in out["reason"]


def test_native_thread_send_is_woken_once_tether_delivered(monkeypatch, tether):
    from cli.commands import sessions_native_delivery as delivery
    from cli.lib import coord_route

    _identity("codex:target", "thread-09")
    _as(monkeypatch, "claude", "native-sender-09")
    monkeypatch.setattr(coord_route, "live_agent_for_session", lambda _thread: "codex:target")
    monkeypatch.setattr(coord_deliver, "state",
                        lambda did: {**tether.records[did], "state": "delivered", "via": "paste", "deliveredAt": 9})
    out = delivery._deliver_live("thread", "Pause", project="fixture", source_key="k12")
    assert out is not None
    assert (out["delivery"], out["observed"], out["wake"]["via"]) == ("woken", False, "paste")


def test_a_finished_service_job_nudges_tether_job_waits(monkeypatch, tmp_path):
    from cli.lib import service_ops

    nudged = []
    monkeypatch.setattr(coord_deliver, "nudge", lambda kind, ref: nudged.append((kind, ref)))
    job_id = "e" * 32
    monkeypatch.setattr(service_ops.service_release, "jobs_root", lambda: tmp_path)
    (tmp_path / f"{job_id}.json").write_text(json.dumps({"job_id": job_id, "state": "queued", "command": ["x"]}))
    monkeypatch.setattr(service_ops.subprocess, "run", lambda *a, **k: __import__("subprocess").CompletedProcess([], 7))
    assert service_ops.run_detached_job(job_id) == 7
    assert nudged == [("job", job_id)]  # failed jobs nudge too
