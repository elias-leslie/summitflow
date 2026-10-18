"""st sessions may-disrupt: one read-only JSON answer for host-level disruption."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cli.lib import coord, coord_disrupt, leases


def _as(monkeypatch, harness: str, sid: str) -> None:
    for name in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "CODEX_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID" if harness == "claude" else "CODEX_THREAD_ID", sid)


def _quiet(_argv):
    return 0, ""


def test_clear_when_nothing_is_running(monkeypatch):
    _as(monkeypatch, "claude", "disrupt-asker-01")
    out = coord_disrupt.snapshot(sessions=lambda: [], running_backups=lambda: [], run=_quiet)
    assert out["schema"] == coord_disrupt.SCHEMA
    assert (out["clear"], out["blocking"], out["unknown"]) == (True, [], [])


def test_objection_and_running_eta_block(monkeypatch):
    _as(monkeypatch, "claude", "disrupt-asker-02")
    a = coord.send("codex:aaaaaa", "Nightshift: reboot in 10 min")
    b = coord.send("codex:bbbbbb", "Nightshift: reboot in 10 min")
    _as(monkeypatch, "codex", "aaaaaa-thread")
    coord.ack(a["id"], "no", "mid migration")
    _as(monkeypatch, "codex", "bbbbbb-thread")
    coord.ack(b["id"], "eta:20")
    _as(monkeypatch, "claude", "disrupt-asker-02")
    out = coord_disrupt.snapshot(request_ids=[a["id"], b["id"]], run=_quiet)
    replies = {r["id"]: r for r in out["handshakes"]}
    assert replies[a["id"]]["reply"] == "no" and replies[b["id"]]["eta_running"]
    assert not out["clear"]
    assert any("objected: mid migration" in line for line in out["blocking"])
    assert any("asked to wait until" in line for line in out["blocking"])


def test_hold_blocks_host_target_unless_holder_said_yes(monkeypatch, tmp_path):
    _as(monkeypatch, "codex", "holder-thread-cccccc")
    holder = leases.acquire_mark("demo-proj", str(tmp_path), "hold", "integration").agent_id
    _as(monkeypatch, "claude", "disrupt-asker-03")
    out = coord_disrupt.snapshot(run=_quiet)
    assert any("demo-proj: repo hold (integration)" in line for line in out["blocking"])
    assert not any("demo-proj" in line for line in coord_disrupt.snapshot("other-proj", run=_quiet)["blocking"])

    sent = coord.send(holder, "Nightshift: reboot; reply yes when checkpointed")
    _as(monkeypatch, "codex", "holder-thread-cccccc")
    coord.ack(sent["id"], "yes")
    _as(monkeypatch, "claude", "disrupt-asker-03")
    out = coord_disrupt.snapshot(request_ids=[sent["id"]], run=_quiet)
    assert not any("demo-proj" in line for line in out["blocking"])


def test_backups_and_unreadable_parts_keep_it_unclear(monkeypatch):
    _as(monkeypatch, "claude", "disrupt-asker-04")

    def run(argv):
        if argv[0] == "ps":
            return 0, "/usr/bin/restic backup /srv\nbash -c 'restic backup'\n"
        if "--user" in argv:
            return 0, "blackbox-archive.service loaded active running Blackbox archive\n"
        return 1, ""

    def down():
        raise RuntimeError("api down")

    out = coord_disrupt.snapshot(sessions=down, running_backups=lambda: [{"id": "b1", "source_id": "pai"}], run=run)
    assert out["backups"]["units"] == ["user:blackbox-archive.service"]
    assert out["backups"]["processes"] == ["/usr/bin/restic backup /srv"]
    assert "backup pai running" in out["blocking"]
    assert "system units unreadable" in out["unknown"]
    assert any("sessions unavailable" in u for u in out["unknown"])
    assert not out["clear"]


def test_agent_hub_sessions_merge_by_handshake_identity(monkeypatch):
    _as(monkeypatch, "claude", "disrupt-asker-05")
    sessions = [
        {"id": "0199aaaa-0000-7000-8000-00000000d00d", "provider": "codex", "status": "active", "host": None,
         "project_id": "agent-hub"},
        {"id": "elsewhere-1", "provider": "claude_code", "status": "active", "host": "other-host"},
    ]
    out = coord_disrupt.snapshot(sessions=lambda: sessions, run=_quiet,
                                 now=datetime.now(UTC) + timedelta(seconds=1))
    row = next(a for a in out["agents"] if a["agent"] == "codex:00d00d")
    assert row["project"] == "agent-hub" and row["source"] == "agent_hub"
    assert "codex:00d00d" in out["unasked"]
    assert not any(a["session"] == "elsewhere-1" for a in out["agents"])
