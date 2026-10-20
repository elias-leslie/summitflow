"""Handshake tuning (owner decisions 2026-10-16): 500-char send, eta lapse, ack wake, one-line mandate."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.tools import app as tools_app
from cli.lib import coord, coord_wake, leases

COORD_INBOX = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "coord_inbox.py"


def _as(monkeypatch, harness: str, sid: str) -> None:
    for name in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID" if harness == "claude" else "CODEX_THREAD_ID", sid)


def _age_ack(message_id: str, minutes: int) -> None:
    with leases._lock("_coord"):
        rows = coord._load_ledger()
        for row in rows:
            if row["id"] == message_id:
                row["acked_at"] = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        coord._save_ledger(rows)


def test_send_takes_up_to_500_chars():
    text = "word " * 99 + "end"  # 498 chars once flattened
    assert coord.send("codex:abcdef", text)["text"] == " ".join(text.split())
    with pytest.raises(ValueError, match="500 chars; put long material in a brief file"):
        coord.send("codex:abcdef", "x" * 501)


def test_lapsed_eta_waits_on_the_receiver_again(monkeypatch):
    _as(monkeypatch, "claude", "eta-sender-01")
    sent = coord.send("codex:abcdef", "can I rebuild agent-hub?")
    _as(monkeypatch, "codex", "abcdef-thread")
    coord.ack(sent["id"], "eta:10")
    assert not [r for r in coord.inbox() if r["id"] == sent["id"]]  # answered for now

    _age_ack(sent["id"], 9)
    _as(monkeypatch, "claude", "eta-sender-01")
    assert next(r for r in coord.inbox() if r["id"] == sent["id"])["state"] == "acked"

    _age_ack(sent["id"], 11)
    _as(monkeypatch, "codex", "abcdef-thread")
    row = next(r for r in coord.inbox() if r["id"] == sent["id"])
    assert (row["state"], row["intent"], row["eta_min"]) == ("open", "eta", 10)
    _as(monkeypatch, "claude", "eta-sender-01")
    assert not any(line.startswith("UNACKED") for line in coord.notices())  # no extra reminder for the sender
    with pytest.raises(ValueError, match="no ack to confirm"):
        coord.confirm(sent["id"])

    _as(monkeypatch, "codex", "abcdef-thread")
    coord.ack(sent["id"], "eta:5")  # a new eta restarts the timer on the same request
    row = next(r for r in coord._load_ledger() if r["id"] == sent["id"])
    assert (row["state"], row["eta_min"]) == ("acked", 5)
    _as(monkeypatch, "claude", "eta-sender-01")
    assert coord.confirm(sent["id"])["state"] == "closed"


def test_lapsed_eta_can_still_be_withdrawn(monkeypatch):
    _as(monkeypatch, "claude", "eta-sender-02")
    sent = coord.send("codex:abcdef", "is gen.json yours?")
    _as(monkeypatch, "codex", "abcdef-thread")
    coord.ack(sent["id"], "eta:1")
    _age_ack(sent["id"], 2)
    _as(monkeypatch, "claude", "eta-sender-02")
    assert coord.confirm(sent["id"], withdraw=True)["withdrawn"] is True


@pytest.fixture
def inbox_module(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("coord_inbox_under_test", COORD_INBOX)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # The script takes the backend path as argv[1] at import; pytest's argv has no such slot.
    monkeypatch.setattr("sys.argv", [str(COORD_INBOX), str(COORD_INBOX.parents[2] / "backend")])
    spec.loader.exec_module(module)
    monkeypatch.setattr(coord_wake, "STATE", tmp_path / "state")
    monkeypatch.setattr(module, "STATE", tmp_path / "state")
    monkeypatch.setattr(module, "POLL", 0.01)
    monkeypatch.setattr(module, "WATCH_SECONDS", 0.2)
    monkeypatch.setattr(module, "memory", lambda *_a, **_k: None)
    monkeypatch.setenv("TMUX", "/sock,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    return module


def test_lapsed_eta_request_line_says_so(monkeypatch, inbox_module):
    _as(monkeypatch, "claude", "eta-sender-03")
    sent = coord.send("codex:abcdef", "may I commit backend/a.py?")
    _as(monkeypatch, "codex", "abcdef-thread")
    coord.ack(sent["id"], "eta:3")
    _age_ack(sent["id"], 4)
    _agent, items = inbox_module.pending()
    assert next(line for key, line, _ in items if key == f"{sent['id']}:req").startswith(
        f"REQUEST {sent['id']} from cc:eta-se (your eta:3 ran out): may I commit")


def test_claude_watcher_wakes_the_sender_for_an_ack_without_typing_into_its_pane(monkeypatch, capsys, inbox_module):
    # The wake stays asyncRewake (claude-config labels it a plain notice); agent text is never typed as a user prompt.
    ack = ("ab12:ack:t1", "ACK ab12 yes from codex:abcdef | close with `st sessions confirm ab12`", False)
    monkeypatch.setattr(inbox_module, "pending", lambda: ("cc:sender", [ack]))
    monkeypatch.setattr(coord_wake, "type_line", lambda *_a: pytest.fail("Claude acks never type into the pane"))
    assert inbox_module.watch("claude_code") == 2
    assert "st coordination (update on a request you sent):\nACK ab12 yes" in capsys.readouterr().err
    assert "ab12:ack:t1" in json.loads(coord_wake.seen_path("cc:sender").read_text())


def test_ack_reason_is_normalized_and_reaches_the_sender_wake(monkeypatch, inbox_module):
    _as(monkeypatch, "claude", "note-sender-01")
    sent = coord.send("codex:abcdef", "may I rebuild summitflow?")
    _as(monkeypatch, "codex", "abcdef-thread")
    reason = "This service is in use. " * 8
    coord.ack(sent["id"], "no", "\n" + reason)
    _as(monkeypatch, "claude", "note-sender-01")
    _agent, items = inbox_module.pending()
    line = coord_wake.pane_line(inbox_module.render([i for i in items if i[0].startswith(sent["id"])]), 0)
    assert reason.strip() in line  # the reason itself, not the generic inbox pointer


def test_claude_watcher_still_wakes_the_receiver_for_a_request(monkeypatch, capsys, inbox_module):
    req = ("cd34:req", "REQUEST cd34 from cc:x: may I rebuild? | answer now with `st sessions ack cd34 ...`", False)
    monkeypatch.setattr(inbox_module, "pending", lambda: ("cc:receiver", [req]))
    monkeypatch.setattr(coord_wake, "type_line", lambda *_a: pytest.fail("a request wakes via asyncRewake"))
    assert inbox_module.watch("claude_code") == 2
    assert "REQUEST cd34" in capsys.readouterr().err


def test_sessions_mandate_is_one_line():
    result = CliRunner().invoke(tools_app, ["manifest", "--density", "full", "--format", "json"])
    assert result.exit_code == 0, result.output
    rows = {row["surface"]: row for row in json.loads(result.output)["tools"]}
    assert "st.sessions.ack" not in rows and "st.sessions.confirm" not in rows
    send = rows["st.sessions.send"]
    assert "500" in send["when"] and "st sessions confirm ID" in send["cmd"] and "eta:MIN" in send["cmd"]
    assert len(send["precautions"]) == 1 and "st lease --hold" in send["precautions"][0]
