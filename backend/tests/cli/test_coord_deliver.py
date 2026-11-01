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
        self.waits: dict[str, list[dict[str, Any]]] | None = {}  # widget -> GET /v1/sessions/:id/waits?recent=1 items
        self.ride_text: dict[str, str] = {}  # widget -> the ride-along text GET /v1/sessions/:id/due?ride=1 takes

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
        if method == "GET" and path.endswith("/waits?recent=1"):
            if self.waits is None:
                raise ConnectionRefusedError
            return 200, {"items": self.waits.get(path.split("/")[3], [])}
        if method == "GET" and path.endswith("/due?ride=1"):
            return 200, {"text": self.ride_text.pop(path.split("/")[3], None)}
        if method == "GET" and path.endswith("/due?ride=peek"):
            text = self.ride_text.get(path.split("/")[3])
            return 200, {"text": text, "token": "aaaaaaaaaaaa.0123abcd" if text else None}
        if method == "DELETE" and "/due?token=" in path:
            return 200, {"taken": 1 if self.ride_text.pop(path.split("/")[3], None) else 0}
        if path == "/v1/waits/check":
            return 200, {"kind": body["kind"], "ref": body["ref"], "armed": 0}
        if method == "DELETE" and "/deliveries?source=" in path:
            return 200, {"sessionId": path.split("/")[3], "source": path.split("source=", 1)[1], "withdrawn": 1,
                         "sending": False}
        return 404, {"error": "not_found"}

    def posts(self) -> list[tuple[str, dict[str, Any]]]:
        return [(path, body) for method, path, body in self.calls if method == "POST" and path.endswith("/deliveries")]

    def withdrawals(self) -> list[str]:
        return [path for method, path, _ in self.calls if method == "DELETE"]

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
        "[Message] Ack from codex:target · a memory notice for this pane · st sessions inbox")
    coord_wake.mark_woke("cc:sender", [])  # woke state does not hide content; seen state does
    coord_wake.STATE.mkdir(parents=True, exist_ok=True)
    coord_wake.seen_path("cc:sender").write_text(json.dumps({f"{row['id']}:ack:{row['acked_at']}": time.time()}))
    assert _line("cc:sender") is None


def _titled(monkeypatch, titles: dict[str, str]) -> None:
    """Tether's session catalog: each widget's displayTitle."""
    monkeypatch.setattr(coordinators, "sessions", _Catalog({w: {"id": w, "displayTitle": t} for w, t in titles.items()}))


class _Catalog:
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.rows = rows

    def __call__(self) -> dict[str, dict[str, Any]]:
        return self.rows

    def cache_clear(self) -> None:
        pass


def test_the_line_names_each_sender_by_its_window_title(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    _identity("cc:sender", "sender-session", anchor=SENDER_ANCHOR)
    _titled(monkeypatch, {OTHER: "Neri \u2014 Neri P2a final native acceptance"})
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("cc:sender", "", "sender-session", "claude_code"))
    coord.send("codex:target", "secret plan")
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("cc:abcdef", "", "abcdef-1", "claude_code"))  # no window
    coord.send("codex:target", "other secret")
    line = _line("codex:target")
    assert line == ('[Message] 2 requests from "Neri P2a final native acceptance" (cc:sender), cc:abcdef'
                    " · st sessions inbox")
    assert "secret" not in line


def test_one_request_reads_request_from_its_window(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    _identity("cc:sender", "sender-session", anchor=SENDER_ANCHOR)
    _titled(monkeypatch, {OTHER: 'SummitFlow \u2014 A "quoted"\ttitle that runs on well past the forty-char cap'})
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("cc:sender", "", "sender-session", "claude_code"))
    coord.send("codex:target", "may I rebuild?")
    line = _line("codex:target")
    assert line == "[Message] Request from \"A 'quoted' title that runs on well past\u2026\" (cc:sender) · st sessions inbox"
    assert len(line) <= coord_deliver.LINE_MAX


def test_titles_go_before_names_when_the_line_is_too_long(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    _identity("cc:sender", "sender-session", anchor=SENDER_ANCHOR)
    _titled(monkeypatch, {OTHER: "T" * 40})
    monkeypatch.setattr(coord_deliver, "LINE_MAX", 60)
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("cc:sender", "", "sender-session", "claude_code"))
    coord.send("codex:target", "may I rebuild?")
    assert _line("codex:target") == "[Message] Request from cc:sender · st sessions inbox"


def test_ids_that_are_not_agent_ids_are_never_put_on_the_line(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    coord.send("codex:target", "x", sender="cc:ok/../rm -rf")
    assert _line("codex:target") == "[Message] Request from another agent · st sessions inbox"


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
    assert body == {"source": "coord:codex:target", "line": "[Message] Request from cc:sender · st sessions inbox"}
    assert f"{row['id']}:req" in coord_wake.load_woke("codex:target")


def test_an_agy_recipient_gets_the_line_on_its_window(monkeypatch, tether):
    _identity("agy:abc123", "agy-conversation-1")
    coord.send("agy:abc123", "hello", sender="cc:sender")
    assert coord_deliver.wake("agy:abc123", ["k:req"])
    assert tether.posts()[0][1]["source"] == "coord:agy:abc123"
    assert "k:req" in coord_wake.load_woke("agy:abc123")


def test_a_session_prefix_address_wakes_the_identity_it_names(monkeypatch, tether):
    _identity("cc:c9ffbd", "c9ffbd05-c536-446f-82f7-30690775f33e")
    _as(monkeypatch, "claude", "sender-02")
    coord.send("c9ffbd05-c536-4", "hello")
    assert coord_deliver.wake("c9ffbd05-c536-4", ["x:req"])
    assert tether.posts()[0][1]["source"] == "coord:cc:c9ffbd"
    assert "x:req" in coord_wake.load_woke("cc:c9ffbd")


@pytest.mark.parametrize("case", ["old_tether", "no_window", "remote", "refused", "gone", "nested"])
def test_unresolved_recipients_keep_todays_path(monkeypatch, tether, case):
    target = {"remote": "a810c7e0@agent-work"}.get(case, "codex:target")
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
    acked = runner.invoke(app, ["sessions", "ack", row["id"], "yes", "go ahead"])
    assert acked.exit_code == 0, acked.output
    assert "Tether delivers a [Message] line about the ack to cc:sender" in acked.output
    assert [(path.split("/")[3], body["source"]) for path, body in tether.posts()] == [
        (WIDGET, "coord:codex:target"), (OTHER, "coord:cc:sender")]
    assert tether.posts()[1][1]["line"] == "[Message] Ack from codex:target · st sessions inbox"
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


# ---------------------------------------------------------------- stale lines


def test_a_line_nothing_waits_for_any_more_is_withdrawn_once(monkeypatch, tether):
    tether.version = 18
    _identity("codex:target", "019a-target")
    _as(monkeypatch, "claude", "sender-09")
    row = coord.send("codex:target", "rebuild ok?")
    assert coord_deliver.wake("codex:target", [f"{row['id']}:req"])
    assert coord_deliver.withdraw_stale("codex:target") is None  # the request still waits
    assert tether.withdrawals() == []
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("codex:target", "", "019a-target", "codex"))
    coord.ack(row["id"], "yes", "go")
    assert coord_deliver.withdraw_stale("codex:target") is True
    assert tether.withdrawals() == [f"/v1/sessions/{WIDGET}/deliveries?source=coord%3Acodex%3Atarget"]
    assert coord_deliver.withdraw_stale("codex:target") is None  # nothing queued since
    assert len(tether.withdrawals()) == 1


def test_a_line_merged_in_during_the_withdraw_is_queued_again(monkeypatch, tether):
    tether.version = 18
    _identity("codex:target", "019a-target")
    coord_wake.mark_woke("codex:target", ["old:req"])
    answers = iter([None])  # nothing waiting at the read; a sender's request lands before the DELETE
    monkeypatch.setattr(coord_deliver, "compose", lambda who, **k: next(
        answers, coord_deliver.Line("[Message] Request from cc:x · st sessions inbox", False)))
    posts = len(tether.posts())
    assert coord_deliver.withdraw_stale("codex:target") is True
    assert len(tether.withdrawals()) == 1
    assert len(tether.posts()) == posts + 1  # queued again, not lost


def test_no_withdraw_before_tether_api_18_or_without_a_queued_line(monkeypatch, tether):
    _identity("codex:target", "019a-target")
    assert coord_deliver.withdraw_stale("codex:target") is None  # never queued: no request at all
    coord_wake.mark_woke("codex:target", ["x:req"])
    tether.version = 17
    assert coord_deliver.withdraw_stale("codex:target") is None
    assert tether.withdrawals() == []


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
    req = inbox.Item("cd34:req", "REQUEST cd34 from cc:x: may I rebuild?", False)
    coord.send("codex:target", "may I rebuild?", sender="cc:x")
    monkeypatch.setattr(inbox, "pending", lambda: ("codex:target", [req]))
    assert inbox.watch(provider) == 0  # no asyncRewake exit, no typing: it ran to its deadline
    assert capsys.readouterr().err == ""
    assert len(tether.posts()) == 1  # queued once, not every poll
    assert "cd34:req" in coord_wake.load_woke("codex:target")
    assert "cd34:req" not in coord_wake.load_seen("codex:target")  # the turn hook still shows it


def _send_as_cli(monkeypatch, to: str, text: str, sid: str) -> dict[str, Any]:
    """``st sessions send`` from another agent: the ledger row plus the sender's own [Message] line."""
    _as(monkeypatch, "claude", sid)
    monkeypatch.setattr("cli.commands.sessions_fleet._send_across_machines", lambda *a, **k: False)
    result = runner.invoke(app, ["sessions", "send", to, text])
    assert result.exit_code == 0, result.output
    return next(r for r in reversed(coord._load_ledger()) if r["text"] == text)


def _age(message_id: str, seconds: float, field: str = "created") -> None:
    from datetime import UTC, datetime, timedelta

    with leases._lock("_coord"):
        rows = coord._load_ledger()
        for row in rows:
            if row["id"] == message_id:
                row[field] = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
        coord._save_ledger(rows)


def test_an_open_request_the_sender_woke_for_never_queues_a_second_line(monkeypatch, inbox, tether):
    # 2026-11-01: an idle wake reminded every REMIND s for a request still open; each was a full turn.
    _identity("codex:target", "target-06")
    row = _send_as_cli(monkeypatch, "codex:target", "may I rebuild?", "sender-06")
    assert len(tether.posts()) == 1  # the sender's line: the one wake
    _age(row["id"], inbox.REMIND + 60)
    with coord_wake._woke_lock("codex:target"):  # the line went out long ago
        coord_wake._save_woke("codex:target", {f"{row['id']}:req": time.time() - inbox.REMIND - 30})
    _as(monkeypatch, "codex", "target-06")
    for provider in ("claude_code", "codex"):
        assert inbox.watch(provider) == 0
    assert len(tether.posts()) == 1


def test_a_request_shown_in_a_turn_never_wakes_the_agent_again(monkeypatch, inbox, tether, capsys):
    tether.version = 15  # no Tether line: the watcher's own wake is the only one
    row = coord.send("cc:receiver", "may I rebuild?", sender="cc:x")
    _age(row["id"], 60)
    monkeypatch.setattr(inbox.leases, "identify_agent", lambda **_: ("cc:receiver", "", "receiver-1", "claude_code"))
    monkeypatch.setattr(inbox.leases, "self_ids", lambda: {"cc:receiver"})
    monkeypatch.setattr(inbox.coord.leases, "identify_agent", inbox.leases.identify_agent)
    _, items = inbox.pending()
    inbox.mark("cc:receiver", items, "claude_code-PostToolUse")  # its turn hook showed it
    future = time.time() + inbox.REMIND + 1
    assert inbox.wakeable("cc:receiver", items, now=future) == []
    assert inbox.due("cc:receiver", items) == []  # and turns remind only after REMIND
    assert inbox.watch("claude_code") == 0 and capsys.readouterr().err == ""


def test_a_new_request_still_wakes_once(monkeypatch, inbox, tether):
    _identity("codex:target", "target-11")
    first = _send_as_cli(monkeypatch, "codex:target", "may I rebuild?", "sender-11")
    second = _send_as_cli(monkeypatch, "codex:target", "may I deploy?", "abcdef-11")
    assert [body["line"] for _, body in tether.posts()] == [
        "[Message] Request from cc:sender · st sessions inbox",
        "[Message] 2 requests from cc:sender, cc:abcdef · st sessions inbox"]
    _as(monkeypatch, "codex", "target-11")
    monkeypatch.setattr(inbox, "GRACE", 0.0)
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 2  # both lines were the senders'
    woke = coord_wake.load_woke("codex:target")
    assert {f"{first['id']}:req", f"{second['id']}:req"} <= set(woke)


def test_the_watcher_wakes_once_when_the_senders_line_did_not_go(monkeypatch, inbox, tether):
    _identity("codex:target", "target-12")
    row = coord.send("codex:target", "may I rebuild?", sender="cc:x")  # recorded, no sender line
    _age(row["id"], 30)
    _as(monkeypatch, "codex", "target-12")
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 1
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 1  # a later watcher: still one


def test_the_watcher_leaves_a_fresh_item_to_its_senders_line(monkeypatch, inbox, tether):
    # 2026-10-31: a watcher read the ledger row before the sender recorded its line and woke the agent itself.
    _identity("codex:target", "target-13")
    row = coord.send("codex:target", "may I rebuild?", sender="cc:x")
    _as(monkeypatch, "codex", "target-13")
    _, items = inbox.pending()
    now = time.time()
    assert inbox.wakeable("codex:target", items, now=now) == []
    assert inbox.settling(items, now=now) == pytest.approx(items[0].at + inbox.GRACE)
    assert inbox.watch("claude_code") == 0 and tether.posts() == []  # inside GRACE the whole run
    coord_wake.mark_woke("codex:target", [f"{row['id']}:req"])  # the sender's line, a moment late
    assert inbox.wakeable("codex:target", items, now=now + inbox.GRACE + 1) == []


def test_an_ack_wakes_its_sender_once(monkeypatch, inbox, tether):
    _identity("cc:sender", "sender-14", anchor=SENDER_ANCHOR)
    _identity("codex:target", "target-14")
    row = _send_as_cli(monkeypatch, "codex:target", "may I rebuild?", "sender-14")
    _as(monkeypatch, "codex", "target-14")
    acked = runner.invoke(app, ["sessions", "ack", row["id"], "yes", "go ahead"])
    assert acked.exit_code == 0, acked.output
    assert [body["source"] for _, body in tether.posts()] == ["coord:codex:target", "coord:cc:sender"]
    _age(row["id"], 60, "acked_at")  # the key carries acked_at: shift the woke record with it
    [ack] = [r for r in coord._load_ledger() if r["id"] == row["id"]]
    with coord_wake._woke_lock("cc:sender"):
        coord_wake._save_woke("cc:sender", {f"{row['id']}:ack:{ack['acked_at']}": time.time() - 30})
    _as(monkeypatch, "claude", "sender-14")
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 2


def _reply_wait(ref: str, state: str = "armed", until: str = "acked", outcome: str | None = None,
                host: str | None = None) -> dict[str, Any]:
    return {"id": "0123456789ab", "waiter": ANCHORS[SENDER_ANCHOR], "kind": "reply", "ref": ref, "host": host,
            "until": until, "state": state, "outcome": outcome}


def _ack_as_cli(monkeypatch, row: dict[str, Any], sid: str, *note: str) -> None:
    _as(monkeypatch, "codex", sid)
    acked = runner.invoke(app, ["sessions", "ack", row["id"], "yes", *note])
    assert acked.exit_code == 0, acked.output


@pytest.mark.parametrize("wait", [{}, {"state": "fired", "outcome": "until"}], ids=["armed", "fired"])
def test_an_ack_its_sender_waits_on_wakes_it_once_through_the_wait(monkeypatch, inbox, tether, wait):
    # 2026-11-01: st aico wait reply REQ woke the sender with [Ready] and the ack's [Message] line, two lines.
    tether.version = 18  # nudges (API 17)
    _identity("cc:sender", "sender-17", anchor=SENDER_ANCHOR)
    _identity("codex:target", "target-17")
    row = _send_as_cli(monkeypatch, "codex:target", "may I rebuild?", "sender-17")
    assert tether.waits is not None
    tether.waits[ANCHORS[SENDER_ANCHOR]] = [_reply_wait(row["id"], **wait)]
    _ack_as_cli(monkeypatch, row, "target-17")
    assert [body["source"] for _, body in tether.posts()] == ["coord:codex:target"]  # the request's line only
    assert tether.nudges() == [{"kind": "reply", "ref": row["id"]}]  # the wait fires now
    [ack] = [r for r in coord._load_ledger() if r["id"] == row["id"]]
    key = f"{row['id']}:ack:{ack['acked_at']}"
    assert key in coord_wake.load_woke("cc:sender")
    _as(monkeypatch, "claude", "sender-17")
    monkeypatch.setattr(inbox, "GRACE", 0.0)
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 1  # nor does its own watcher line it
    with coord_wake._woke_lock("cc:sender"):  # the sender's mark was lost: its watcher still leaves it to the wait
        coord_wake._save_woke("cc:sender", {})
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 1
    assert key in coord_wake.load_woke("cc:sender")
    _, items = inbox.pending()
    assert [item.key.split(":")[1] for item in items] == ["ack"]  # the turn hook still shows the answer


@pytest.mark.parametrize("wait", [
    {"until": "closed"}, {"state": "cancelled"}, {"state": "timed_out", "outcome": "timeout"}, {"host": "gem"}, None,
], ids=["until-closed", "cancelled", "timed-out", "other-host", "no-answer"])
def test_an_ack_no_reply_wait_reports_still_gets_its_line(monkeypatch, inbox, tether, wait):
    _identity("cc:sender", "sender-18", anchor=SENDER_ANCHOR)
    _identity("codex:target", "target-18")
    row = _send_as_cli(monkeypatch, "codex:target", "may I rebuild?", "sender-18")
    if wait is None:
        tether.waits = None  # GET waits fails: today's line
    elif tether.waits is not None:
        tether.waits[ANCHORS[SENDER_ANCHOR]] = [_reply_wait(row["id"], **wait)]
    _ack_as_cli(monkeypatch, row, "target-18", "go ahead")
    assert [body["source"] for _, body in tether.posts()] == ["coord:codex:target", "coord:cc:sender"]
    assert tether.posts()[1][1]["line"] == "[Message] Ack from codex:target · st sessions inbox"


def test_a_line_leaves_out_only_the_ack_a_wait_reports(monkeypatch, tether):
    _identity("cc:sender", "sender-19", anchor=SENDER_ANCHOR)
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("cc:sender", "", "sender-19", "claude_code"))
    waited = coord.send("codex:target", "may I rebuild?")
    other = coord.send("codex:target", "may I deploy?")
    coord.send("cc:sender", "a question back", sender="cc:abcdef")
    monkeypatch.setattr(leases, "identify_agent", lambda **_: ("codex:target", "", "target-19", "codex"))
    coord.ack(waited["id"], "yes")
    coord.ack(other["id"], "no", "busy")
    assert tether.waits is not None
    tether.waits[ANCHORS[SENDER_ANCHOR]] = [_reply_wait(waited["id"])]
    assert _line("cc:sender") == "[Message] Request from cc:abcdef · Ack from codex:target · st sessions inbox"


def test_an_eta_that_ran_out_wakes_once_more(monkeypatch, inbox, tether):
    _identity("codex:target", "target-15")
    row = _send_as_cli(monkeypatch, "codex:target", "may I rebuild?", "sender-15")
    _as(monkeypatch, "codex", "target-15")
    coord.ack(row["id"], "eta:3")
    _age(row["id"], 4 * 60, "acked_at")
    _age(row["id"], 5 * 60)
    with coord_wake._woke_lock("codex:target"):
        coord_wake._save_woke("codex:target", {f"{row['id']}:req": time.time() - 5 * 60 + 1})
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 2  # the lapse is news
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == 2  # once


def _holder(tmp_path: Path, script_dir: Path, lock: Path):
    """A process that looks like a watcher started from ``script_dir`` and holds ``lock``."""
    import subprocess
    import sys

    script_dir.mkdir(parents=True, exist_ok=True)
    script = script_dir / "coord_inbox.py"
    script.write_text("import fcntl, sys, time\nf = open(sys.argv[2], 'w')\nfcntl.flock(f, fcntl.LOCK_EX)\n"
                      "print('held', flush=True)\ntime.sleep(60)\n")
    proc = subprocess.Popen([sys.executable, "-I", str(script), "watch", str(lock)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout and proc.stdout.readline().strip() == "held"
    return proc


def test_a_watcher_from_another_release_hands_over_the_lock(inbox, tmp_path):
    # 2026-10-31: watchers started before a deploy kept the old wake rules for up to 6 h.
    lock_path = tmp_path / "cc_x.claude_code-watch.lock"
    old = _holder(tmp_path, tmp_path / "releases" / "old" / "scripts" / "lib", lock_path)
    try:
        with open(lock_path, "w") as lock:
            assert inbox._lock_holder(lock) == old.pid
            assert inbox.take_over(lock) is True
        assert old.wait(timeout=5) != 0
    finally:
        old.kill()


def test_a_watcher_of_the_same_release_keeps_the_lock(inbox, tmp_path, monkeypatch):
    lock_path = tmp_path / "cc_y.claude_code-watch.lock"
    same = _holder(tmp_path, tmp_path / "same", lock_path)
    monkeypatch.setattr(inbox, "SCRIPT", str((tmp_path / "same" / "coord_inbox.py").resolve()))
    try:
        with open(lock_path, "w") as lock:
            assert inbox.take_over(lock) is False
        assert same.poll() is None
    finally:
        same.kill()


def test_watcher_falls_back_to_the_asyncrewake_wake_without_tether(monkeypatch, inbox, tether, capsys):
    tether.version = 15
    req = inbox.Item("cd34:req", "REQUEST cd34 from cc:x: may I rebuild?", False)
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
    monkeypatch.setattr(inbox, "pending", lambda: ("codex:target", [inbox.Item("ab01:req", "REQUEST ab01", False)]))
    assert inbox.watch("codex") == 0 and capsys.readouterr().err == ""  # type_line would fail the test
    assert len(tether.posts()) > 1  # tried again
    assert coord_wake.load_woke("codex:target") == {}


def test_a_watcher_left_from_before_a_context_reset_exits(monkeypatch, inbox, tether):
    _identity("cc:before", "before-clear", last="2026-10-31T10", main=True)
    _identity("cc:after", "after-clear", last="2026-10-31T11", main=True)
    coord.send("cc:before", "hi", sender="cc:x")
    monkeypatch.setattr(inbox, "WATCH_SECONDS", 30)
    monkeypatch.setattr(inbox, "pending", lambda: ("cc:before", [inbox.Item("ab02:req", "REQUEST ab02", False)]))
    assert inbox.watch("claude_code") == 0 and tether.posts() == []  # cc:after's own watcher wakes it


def test_pi_idle_check_skips_items_a_tether_line_wakes_it_for(monkeypatch, inbox, tether, capsys):
    req = inbox.Item("aa11:req", "REQUEST aa11 from cc:x: hi", False)
    monkeypatch.setattr(inbox, "pending", lambda: ("pi:target", [req]))
    monkeypatch.setattr(inbox.coord, "adopt_hook_identity", lambda payload: None)
    monkeypatch.setattr(inbox.coord_lineage, "observe", lambda **_: [])
    monkeypatch.setattr("sys.argv", [str(COORD_INBOX), "backend", "turn", "pi"])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"hook_event_name": "PiIdle"})))
    coord_wake.mark_woke("pi:target", ["aa11:req"])
    assert inbox.main() == 0 and capsys.readouterr().out == ""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"hook_event_name": "PostToolUse"})))
    assert inbox.main() == 0 and "REQUEST aa11" in capsys.readouterr().out  # its turn hook still shows it


# ---------------------------------------------------------------- delivery classes (Tether API 24)


def _pair(monkeypatch, tether, sid: str = "sender-30", version: int = 24) -> None:
    tether.version = version
    _identity("cc:sender", sid, anchor=SENDER_ANCHOR)
    _identity("codex:target", "target-30")


def _fyi_as_cli(monkeypatch, to: str, text: str, sid: str) -> dict[str, Any]:
    _as(monkeypatch, "claude", sid)
    result = runner.invoke(app, ["sessions", "send", to, text, "--fyi"])
    assert result.exit_code == 0, result.output
    return next(r for r in reversed(coord._load_ledger()) if r["text"] == text)


def test_a_request_is_a_wake_and_names_the_windows_that_sent_it(monkeypatch, tether):
    # Owner example: a lane told to pause answers "paused, nothing running"; that message is the wake and
    # Tether learns from it that the lane told its launcher, so the went-idle line is dropped.
    _pair(monkeypatch, tether)
    _send_as_cli(monkeypatch, "codex:target", "paused, nothing running", "sender-30")
    [(path, body)] = tether.posts()
    assert path == f"/v1/sessions/{WIDGET}/deliveries"
    assert "ride" not in body and body["from"] == [OTHER]
    assert body["line"] == "[Message] Request from cc:sender · st sessions inbox"


def test_an_older_tether_gets_a_plain_line(monkeypatch, tether):
    _pair(monkeypatch, tether, version=23)
    _send_as_cli(monkeypatch, "codex:target", "paused, nothing running", "sender-30")
    _fyi_as_cli(monkeypatch, "codex:target", "also fine", "sender-30")
    assert all(set(body) == {"source", "line"} for _, body in tether.posts())


def test_a_bare_yes_closes_for_its_sender_and_rides_along(monkeypatch, tether):
    # Owner example: "Woken by an Aico notice and nothing to do" was a bare ack woken as a full turn.
    _pair(monkeypatch, tether)
    row = _send_as_cli(monkeypatch, "codex:target", "pause please", "sender-30")
    _ack_as_cli(monkeypatch, row, "target-30")
    [ledger] = [r for r in coord._load_ledger() if r["id"] == row["id"]]
    assert ledger["state"] == "closed" and ledger["auto_closed"] and ledger["intent"] == "yes"
    assert ledger["acked_by"] == "codex:target" and ledger["acked_at"]
    second = tether.posts()[1][1]
    assert second["source"] == "coord:cc:sender" and second["ride"] is True and "from" not in second
    assert second["line"] == "[Message] Ack from codex:target (closed) · st sessions inbox"
    # No third step: the sender's confirm is a quiet no-op, and its inbox has nothing to answer.
    _as(monkeypatch, "claude", "sender-30")
    done = runner.invoke(app, ["sessions", "confirm", row["id"]])
    assert done.exit_code == 0 and coord._load_ledger()[0]["state"] == "closed"


@pytest.mark.parametrize("answer", [("yes", "go ahead"), ("no", "busy"), ("eta:5", None)],
                         ids=["note", "no", "eta"])
@pytest.mark.parametrize("version", [24, 25])
def test_acks_with_a_note_a_no_or_an_eta_stay_wakes(monkeypatch, tether, answer, version):
    # Review P1-3: an ack (an eta, "yes, starting") may open a turn of work, so it never counts as the acker telling
    # the requester: from API 25 it names its window as a reply (an act on the requester), before that none.
    _pair(monkeypatch, tether, version=version)
    row = _send_as_cli(monkeypatch, "codex:target", "pause please", "sender-30")
    _as(monkeypatch, "codex", "target-30")
    args = ["sessions", "ack", row["id"], answer[0], *([answer[1]] if answer[1] else [])]
    assert runner.invoke(app, args).exit_code == 0
    [ledger] = [r for r in coord._load_ledger() if r["id"] == row["id"]]
    assert ledger["state"] == "acked"
    second = tether.posts()[1][1]
    assert "ride" not in second
    if version >= 25:
        assert second["from"] == [WIDGET] and second["reply"] is True
    else:
        assert "from" not in second and "reply" not in second
    assert second["line"] == "[Message] Ack from codex:target · st sessions inbox"


@pytest.mark.parametrize("wait", [{}, {"state": "fired", "outcome": "until"}], ids=["armed", "fired"])
def test_a_bare_yes_its_sender_waits_on_stays_open_for_the_wait(monkeypatch, tether, wait):
    _pair(monkeypatch, tether)
    row = _send_as_cli(monkeypatch, "codex:target", "pause please", "sender-30")
    assert tether.waits is not None
    tether.waits[ANCHORS[SENDER_ANCHOR]] = [_reply_wait(row["id"], **wait)]
    _ack_as_cli(monkeypatch, row, "target-30")
    [ledger] = [r for r in coord._load_ledger() if r["id"] == row["id"]]
    assert ledger["state"] == "acked" and not ledger.get("auto_closed")
    assert [body["source"] for _, body in tether.posts()] == ["coord:codex:target"]  # the wait is the one wake


def test_a_bare_yes_from_a_host_window_keeps_its_ack_path(monkeypatch, tether):
    row = coord.send("cc:4a9a07", "can I deploy?", sender="cc:hostagent@agent-work",
                     remote={"host": "agent-work", "reply_window": "a810c7e0"})
    acked = coord.ack(row["id"], "yes", remote=("cc:4a9a07", "cc:4a9a07"))
    assert coord_deliver.settle_bare_ack(acked)["state"] == "acked"


def test_a_closed_ack_is_shown_once_and_never_wakes_an_idle_agent(monkeypatch, inbox, tether, capsys):
    _pair(monkeypatch, tether)
    row = _send_as_cli(monkeypatch, "codex:target", "pause please", "sender-30")
    _ack_as_cli(monkeypatch, row, "target-30")
    posts = len(tether.posts())
    _as(monkeypatch, "claude", "sender-30")
    _, items = inbox.pending()
    [item] = items
    assert item.ride and item.key.startswith(f"{row['id']}:ack:") and "closed; nothing to do" in item.line
    assert inbox.wakeable("cc:sender", items, now=time.time() + 60) == []
    monkeypatch.setattr(inbox, "GRACE", 0.0)
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == posts  # the watcher leaves it
    assert inbox.due("cc:sender", items) == items
    inbox.mark("cc:sender", items)
    assert inbox.due("cc:sender", items) == []
    assert "FYI" in inbox.render(items) or "nothing to answer" in inbox.render(items)


def test_an_fyi_is_ride_along_and_needs_no_ack_or_confirm(monkeypatch, tether):
    _pair(monkeypatch, tether)
    row = _fyi_as_cli(monkeypatch, "codex:target", "paused, nothing running", "sender-30")
    assert row["state"] == "fyi"
    [(_, body)] = tether.posts()
    assert body["ride"] is True and body["from"] == [OTHER]  # its sender acted on the recipient; never "told"
    assert body["line"] == "[Message] FYI from cc:sender · st sessions inbox"
    assert "paused" not in body["line"]
    _as(monkeypatch, "codex", "target-30")
    acked = runner.invoke(app, ["sessions", "ack", row["id"], "yes"])
    assert acked.exit_code == 2 and "FYI note" in acked.output
    _as(monkeypatch, "claude", "sender-30")
    confirmed = runner.invoke(app, ["sessions", "confirm", row["id"]])
    assert confirmed.exit_code == 2 and "FYI note" in confirmed.output


def test_an_fyi_alongside_a_request_joins_its_wake_line(monkeypatch, tether):
    _pair(monkeypatch, tether)
    _fyi_as_cli(monkeypatch, "codex:target", "status note", "sender-30")
    _send_as_cli(monkeypatch, "codex:target", "please look", "sender-30")
    first, second = (body for _, body in tether.posts())
    assert first["ride"] is True
    assert "ride" not in second and second["from"] == [OTHER]
    assert second["line"] == "[Message] Request from cc:sender · FYI from cc:sender · st sessions inbox"


def test_an_fyi_is_not_for_fleet_roots_or_agent_hosts(monkeypatch, tether):
    _pair(monkeypatch, tether)
    for extra in (["--delivery", "native-thread"], ["--delivery", "fleet-stream"]):
        result = runner.invoke(app, ["sessions", "send", "codex:target", "x", "--fyi", *extra])
        assert result.exit_code == 2 and "handshake note" in result.output
    monkeypatch.setenv("ST_AGENT_HOST", "agent-work")
    result = runner.invoke(app, ["sessions", "send", "codex:target", "x", "--fyi"])
    assert result.exit_code == 2 and "this computer" in result.output
    assert coord._load_ledger() == []


def test_a_repeated_fyi_is_not_recorded_twice(monkeypatch, tether):
    _pair(monkeypatch, tether)
    first = _fyi_as_cli(monkeypatch, "codex:target", "status note", "sender-30")
    again = _fyi_as_cli(monkeypatch, "codex:target", "status note", "sender-30")
    assert again["id"] == first["id"] and len(coord._load_ledger()) == 1


def _hook(inbox, monkeypatch, capsys, provider: str, event: str) -> str:
    monkeypatch.setattr(inbox.coord, "adopt_hook_identity", lambda payload: None)
    monkeypatch.setattr(inbox.coord_lineage, "observe", lambda **_: [])
    monkeypatch.setattr("sys.argv", [str(COORD_INBOX), "backend", "turn", provider])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"hook_event_name": event})))
    assert inbox.main() == 0
    return capsys.readouterr().out


def test_the_turn_hook_shows_an_fyi_once_and_the_watcher_never_wakes_for_it(monkeypatch, inbox, tether, capsys):
    _pair(monkeypatch, tether)
    row = _fyi_as_cli(monkeypatch, "codex:target", "paused, nothing running", "sender-30")
    posts = len(tether.posts())
    _as(monkeypatch, "codex", "target-30")
    monkeypatch.setattr(inbox, "GRACE", 0.0)
    _, items = inbox.pending()
    [item] = items
    assert item.ride and item.key == f"{row['id']}:fyi" and "paused, nothing running" in item.line
    assert inbox.watch("claude_code") == 0 and len(tether.posts()) == posts
    assert inbox.wakeable("codex:target", items, now=time.time() + 60) == []
    assert "FYI" in inbox.render(items).splitlines()[0]
    # The turn hook shows it, once; Stop does not block on it.
    out = _hook(inbox, monkeypatch, capsys, "codex", "UserPromptSubmit")
    assert "paused, nothing running" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert _hook(inbox, monkeypatch, capsys, "codex", "UserPromptSubmit") == ""
    assert coord.inbox() == []  # shown: it leaves the inbox
    monkeypatch.setattr("sys.argv", [str(COORD_INBOX), "backend", "stop", "claude_code"])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"hook_event_name": "Stop"})))
    assert inbox.main() == 0 and capsys.readouterr().out == ""


@pytest.mark.parametrize("provider", ["claude_code", "codex"])
def test_ride_along_lines_join_the_next_prompt_not_every_tool_result(monkeypatch, inbox, tether, capsys, provider):
    monkeypatch.setenv("AICO_WIDGET_ID", WIDGET)
    tether.version = 24
    _identity("codex:target", "target-31")
    _as(monkeypatch, "codex", "target-31")
    tether.ride_text[WIDGET] = '[Ready] lane "Store lane" went idle again after 2m'
    assert _hook(inbox, monkeypatch, capsys, provider, "PostToolUse") == ""
    assert tether.ride_text  # a tool result never takes them
    out = _hook(inbox, monkeypatch, capsys, provider, "UserPromptSubmit")
    assert "went idle again" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert not tether.ride_text


def test_pi_takes_ride_along_lines_at_its_next_tool_result_and_its_idle_check_does_not(monkeypatch, inbox, tether, capsys):
    monkeypatch.setenv("AICO_WIDGET_ID", WIDGET)
    tether.version = 24
    _identity("pi:target", "target-pi1")
    _as(monkeypatch, "claude", "x")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.setenv("PI_SESSION_ID", "target-pi1")
    tether.ride_text[WIDGET] = "[Ready] lane X went idle again"
    assert _hook(inbox, monkeypatch, capsys, "pi", "PiIdle") == ""
    assert tether.ride_text
    out = _hook(inbox, monkeypatch, capsys, "pi", "PostToolUse")
    assert "went idle again" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_no_ride_flush_before_tether_api_24_or_without_a_window(monkeypatch, inbox, tether, capsys):
    tether.version = 23
    _identity("codex:target", "target-31")
    _as(monkeypatch, "codex", "target-31")
    monkeypatch.setenv("AICO_WIDGET_ID", WIDGET)
    tether.ride_text[WIDGET] = "x"
    assert _hook(inbox, monkeypatch, capsys, "claude_code", "UserPromptSubmit") == ""
    tether.version = 24
    monkeypatch.delenv("AICO_WIDGET_ID")
    assert _hook(inbox, monkeypatch, capsys, "claude_code", "UserPromptSubmit") == ""
    assert not [c for c in tether.calls if c[1].endswith("due?ride=1")]


def test_a_ride_line_left_after_the_wake_went_stale_is_queued_again_as_ride(monkeypatch, tether):
    # A queued request line whose request was answered: gone, but the unseen FYI keeps a line of its own.
    _pair(monkeypatch, tether, version=24)
    req = _send_as_cli(monkeypatch, "codex:target", "please look", "sender-30")
    _fyi_as_cli(monkeypatch, "codex:target", "status note", "sender-30")
    _as(monkeypatch, "codex", "target-30")
    assert runner.invoke(app, ["sessions", "ack", req["id"], "no", "later"]).exit_code == 0
    _age(req["id"], 1)
    coord_wake.mark_woke("codex:target", [f"{req['id']}:req"])
    posts = len(tether.posts())
    assert coord_deliver.withdraw_stale("codex:target") is True
    assert len(tether.withdrawals()) == 1
    reposted = tether.posts()[posts][1]
    assert reposted["ride"] is True and reposted["line"] == "[Message] FYI from cc:sender · st sessions inbox"


def test_a_wake_class_item_still_standing_keeps_its_queued_line(monkeypatch, tether):
    _pair(monkeypatch, tether, version=24)
    _send_as_cli(monkeypatch, "codex:target", "please look", "sender-30")
    _fyi_as_cli(monkeypatch, "codex:target", "status note", "sender-30")
    coord_wake.mark_woke("codex:target", ["x:req"])
    assert coord_deliver.withdraw_stale("codex:target") is None and not tether.withdrawals()


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
                    "line": "[Message] Request from cc:ea3f27 · st sessions inbox"}
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
                    "line": "[Message] Ack from cc:4a9a07 · st sessions inbox"}


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
    coord_remote.ack_from_host(asked["id"], "yes", "ok", sender="cc:hostagent", host="agent-work", window="a810c7e0")
    assert hub.posts()[-1][1] == {"source": "coord:cc:4a9a07", "line": (
        "[Message] Request from cc:hostagent@agent-work · Ack from cc:hostagent@agent-work · st sessions inbox")}
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


# ---------------------------------------------------------------- review fixes (wake trim)


def test_a_line_names_only_the_window_whose_command_queued_it(monkeypatch, tether):
    # Review P2-1: a re-post (the recipient's own watcher, withdraw_stale's re-queue) names no sender, so a request
    # still waiting from an earlier turn never reads as the requester telling the recipient again.
    _pair(monkeypatch, tether)
    _send_as_cli(monkeypatch, "codex:target", "please look", "sender-30")
    assert tether.posts()[0][1]["from"] == [OTHER]
    assert coord_deliver.wake("codex:target") is not None
    again = tether.posts()[1][1]
    assert again["line"] == "[Message] Request from cc:sender · st sessions inbox" and "from" not in again


def test_an_fyi_names_its_sender_as_contact_only(monkeypatch, tether):
    _pair(monkeypatch, tether, version=25)
    _fyi_as_cli(monkeypatch, "codex:target", "status note", "sender-30")
    [(_, body)] = tether.posts()
    assert body["ride"] is True and body["from"] == [OTHER]  # Tether counts a ride line as contact, never as telling


@pytest.mark.parametrize("first_fyi", [True, False], ids=["fyi-then-request", "request-then-fyi"])
def test_a_request_and_an_fyi_with_the_same_text_are_both_recorded(monkeypatch, tether, first_fyi):
    # Review P2-6: de-dup stays within one class.
    _pair(monkeypatch, tether)
    send = (_fyi_as_cli, lambda m, to, text, sid: _send_as_cli(m, to, text, sid))
    first = send[0 if first_fyi else 1](monkeypatch, "codex:target", "done: report at /tmp/r.md", "sender-30")
    second = send[1 if first_fyi else 0](monkeypatch, "codex:target", "done: report at /tmp/r.md", "sender-30")
    assert first["id"] != second["id"] and {first["state"], second["state"]} == {"fyi", "open"}


def test_an_fyi_already_shown_is_a_new_note_when_sent_again(monkeypatch, tether):
    _pair(monkeypatch, tether)
    first = _fyi_as_cli(monkeypatch, "codex:target", "paused, nothing running", "sender-30")
    coord_wake.STATE.mkdir(parents=True, exist_ok=True)
    coord_wake.seen_path("codex:target").write_text(json.dumps({f"{first['id']}:fyi": time.time()}))
    again = _fyi_as_cli(monkeypatch, "codex:target", "paused, nothing running", "sender-30")
    assert again["id"] != first["id"] and not again.get("duplicate")


def test_a_send_tells_how_to_be_woken_by_the_ack(monkeypatch, tether):
    # Review P2-3: a bare yes closes the request without waking its sender; the send says how to wait on it.
    _pair(monkeypatch, tether)
    _as(monkeypatch, "claude", "sender-30")
    monkeypatch.setattr("cli.commands.sessions_fleet._send_across_machines", lambda *a, **k: False)
    result = runner.invoke(app, ["sessions", "send", "codex:target", "may I rebuild?"])
    row = coord._load_ledger()[0]
    assert f"arm st aico wait reply {row['id']}" in result.output


def test_a_nested_harness_never_takes_its_windows_ride_lines(monkeypatch, inbox, tether, capsys):
    # Review P2-4: a claude -p / codex exec an agent runs inherits AICO_WIDGET_ID; the lines are not for it.
    monkeypatch.setenv("AICO_WIDGET_ID", WIDGET)
    tether.version = 25
    _identity("codex:target", "target-32")
    _as(monkeypatch, "codex", "target-32")
    tether.nested.add("4242:99")
    tether.ride_text[WIDGET] = "[Ready] lane X went idle again"
    assert _hook(inbox, monkeypatch, capsys, "codex", "UserPromptSubmit") == ""
    assert tether.ride_text and not [c for c in tether.calls if "/due?" in c[1]]


def test_ride_lines_are_peeked_first_and_taken_only_once_printed(monkeypatch, inbox, tether, capsys):
    # Review P2-5: a hook that times out or dies before printing them loses no line.
    monkeypatch.setenv("AICO_WIDGET_ID", WIDGET)
    tether.version = 25
    _identity("codex:target", "target-33")
    _as(monkeypatch, "codex", "target-33")
    tether.ride_text[WIDGET] = "[Ready] lane X went idle again"
    killed = {"on": True}
    real_emit = inbox.emit

    def emit(*args: Any, **kwargs: Any) -> None:
        if killed["on"]:
            raise TimeoutError("hook killed before it printed")
        real_emit(*args, **kwargs)

    monkeypatch.setattr(inbox, "emit", emit)
    with pytest.raises(TimeoutError):
        _hook(inbox, monkeypatch, capsys, "codex", "UserPromptSubmit")
    assert tether.ride_text  # still queued for the next turn or wake
    killed["on"] = False
    tether.calls.clear()
    coord_wake.mark_woke("codex:target", ["x:req"])  # the hook's withdraw of a stale line runs too
    out = _hook(inbox, monkeypatch, capsys, "codex", "UserPromptSubmit")
    assert "went idle again" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert not tether.ride_text
    # Peeked first, before the hook's slower inbox work (the withdraw); taken only after printing.
    paths = [path for method, path, _ in tether.calls if method in ("GET", "DELETE")]
    assert paths == [f"/v1/sessions/{WIDGET}/due?ride=peek",
                     f"/v1/sessions/{WIDGET}/deliveries?source=coord%3Acodex%3Atarget",
                     f"/v1/sessions/{WIDGET}/due?token=aaaaaaaaaaaa.0123abcd"]


def test_ride_lines_stay_queued_when_little_hook_time_is_left(monkeypatch, inbox, tether, capsys):
    # Review follow-up: killed after the take, the lines would be lost; unconfirmed, they show again next turn.
    monkeypatch.setenv("AICO_WIDGET_ID", WIDGET)
    tether.version = 25
    _identity("codex:target", "target-34")
    _as(monkeypatch, "codex", "target-34")
    tether.ride_text[WIDGET] = "[Ready] lane X went idle again"
    monkeypatch.setattr(inbox, "STARTED", time.monotonic() - inbox.HOOK_SECONDS + 1.0)
    out = _hook(inbox, monkeypatch, capsys, "codex", "UserPromptSubmit")
    assert "went idle again" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert tether.ride_text  # not taken
    assert not [path for method, path, _ in tether.calls if method == "DELETE" and "token=" in path]


def test_send_help_keeps_the_done_report_rule():
    # Review P3-2: the help trim dropped it.
    result = CliRunner().invoke(app, ["sessions", "send", "--help"], env={"COLUMNS": "400"})
    assert result.exit_code == 0
    text = " ".join(result.stdout.replace("│", " ").split())
    assert "A done report, or anything you need answered, is a normal request" in text
