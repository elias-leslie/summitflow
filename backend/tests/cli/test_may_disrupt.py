"""st sessions may-disrupt: one read-only JSON answer for host-level disruption."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from cli.lib import coord, coord_disrupt, coord_lineage, leases


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
    assert "an agent is holding demo-proj (integration)" in out["blocking"]
    assert not any(holder in line for line in out["blocking"])  # owner copy; the id stays in holds
    assert [h["holder"] for h in out["holds"] if h["project"] == "demo-proj"] == [holder]
    assert not any("demo-proj" in line for line in coord_disrupt.snapshot("other-proj", run=_quiet)["blocking"])

    sent = coord.send(holder, "Nightshift: reboot; reply yes when checkpointed")
    _as(monkeypatch, "codex", "holder-thread-cccccc")
    coord.ack(sent["id"], "yes")
    _as(monkeypatch, "claude", "disrupt-asker-03")
    out = coord_disrupt.snapshot(request_ids=[sent["id"]], run=_quiet)
    assert not any("demo-proj" in line for line in out["blocking"])


def test_running_acceptance_says_what_runs_where_without_the_agent_id(monkeypatch, tmp_path):
    _as(monkeypatch, "claude", "acceptance-runner-dddddd")
    mark = leases.acquire_mark("demo-op", str(tmp_path), "op", "acceptance")
    _as(monkeypatch, "claude", "disrupt-asker-05")
    try:
        out = coord_disrupt.snapshot(run=_quiet)
    finally:
        leases.release_mark("demo-op", mark.lease_id)
    assert "acceptance checks running in demo-op" in out["blocking"]
    assert not any(mark.agent_id in line for line in out["blocking"])
    assert {"project": "demo-op", "kind": "op", "holder": mark.agent_id}.items() <= next(
        h for h in out["holds"] if h["project"] == "demo-op").items()


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


def test_live_family_uses_latest_main_registration_not_worker_activity():
    pid = os.getpid()
    start = leases._process_start(pid)
    anchor = f"{pid}:{start}"
    identities = {
        "codex:000001": {"session": "0199aaaa-0000-7000-8000-000000000001", "main": True, "first": "2026-10-19T10:00:00+00:00",
                         "last": "2026-10-20T15:00:00+00:00"},
        "codex:000002": {"session": "0199aaaa-0000-7000-8000-000000000002", "main": True, "first": "2026-10-20T10:00:00+00:00",
                         "last": "2026-10-20T10:00:00+00:00"},
        "codex:000003": {"session": "0199aaaa-0000-7000-8000-000000000003", "first": "2026-10-20T11:00:00+00:00",
                         "last": "2026-10-20T16:00:00+00:00"},
    }
    for row in identities.values():
        row.update(anchor=anchor, provider="codex")
    coord_lineage.save_doc({"identities": identities})
    sessions = [{"id": row["session"], "provider": "codex", "status": "active", "project_id": "summitflow"}
                for row in identities.values()]
    out = coord_disrupt.snapshot(sessions=lambda: sessions, run=_quiet)
    assert out["agents"] == [{
        "agent": "codex:000002", "provider": "codex", "session": "0199aaaa-0000-7000-8000-000000000002", "project": "summitflow",
        "source": "coordination+agent_hub", "last_seen": "2026-10-20T10:00:00+00:00",
        "pid": pid, "pid_start": start,
    }]
    assert out["unasked"] == ["codex:000002"]


def test_unmarked_live_family_and_unregistered_sessions_remain_separate():
    anchor = f"{os.getpid()}:{leases._process_start(os.getpid())}"
    coord_lineage.save_doc({"identities": {
        aid: {"anchor": anchor, "provider": "codex", "session": f"session-{suffix}"}
        for aid, suffix in (("codex:000011", "000011"), ("codex:000012", "000012"))
    }})
    sessions = [{"id": "0199aaaa-0000-7000-8000-000000000013", "provider": "codex", "status": "active"}]
    agents = coord_disrupt.live_agents(sessions, "this-host")
    assert [row["agent"] for row in agents] == ["codex:000011", "codex:000012", "codex:000013"]
    assert all("pid" not in row and "pid_start" not in row for row in agents)


def test_dead_and_reused_anchors_cannot_supply_parent_process_metadata(monkeypatch):
    pid = os.getpid()
    start = leases._process_start(pid)
    real_start = leases._process_start
    dead_pid = pid + 1
    monkeypatch.setattr(leases, "_process_start", lambda candidate: None if candidate == dead_pid else real_start(candidate))
    coord_lineage.save_doc({"identities": {
        "codex:000021": {"anchor": f"{pid}:0", "provider": "codex", "session": "0199aaaa-0000-7000-8000-000000000021", "main": True},
        "codex:000022": {"anchor": f"{dead_pid}:{start}", "provider": "codex", "session": "0199aaaa-0000-7000-8000-000000000022", "main": True},
    }})
    assert coord_disrupt.live_agents([], "this-host") == []
    # Active Hub evidence survives, but it cannot inherit a stale registry's process claim.
    sessions = [{"id": "0199aaaa-0000-7000-8000-000000000021", "provider": "codex", "status": "active"}]
    assert coord_disrupt.live_agents(sessions, "this-host") == [{
        "agent": "codex:000021", "provider": "codex", "session": "0199aaaa-0000-7000-8000-000000000021", "project": None,
        "source": "agent_hub", "last_seen": None,
    }]


def test_everyone_lists_open_requests_from_any_sender(monkeypatch):
    _as(monkeypatch, "claude", "disrupt-other-sender")
    sent = coord.send("codex:dddddd", "Nightshift: restart docker in 2 min")
    _as(monkeypatch, "claude", "runtime-page-reader")
    assert not any(r["id"] == sent["id"] for r in coord_disrupt.snapshot(run=_quiet)["handshakes"])
    page = coord_disrupt.snapshot(everyone=True, run=_quiet)
    assert any(r["id"] == sent["id"] and r["reply"] == "none" for r in page["handshakes"])
    assert "codex:dddddd" in page["awaiting_reply"]


def test_runtime_page_keeps_a_hold_after_its_holder_said_yes_to_someone_else(monkeypatch, tmp_path):
    _as(monkeypatch, "codex", "holder-thread-eeeeee")
    holder = leases.acquire_mark("demo-proj", str(tmp_path), "hold", "integration").agent_id
    _as(monkeypatch, "claude", "disrupt-unrelated-asker")
    sent = coord.send(holder, "may I read your notes file?")
    _as(monkeypatch, "codex", "holder-thread-eeeeee")
    coord.ack(sent["id"], "yes")
    _as(monkeypatch, "claude", "runtime-page-reader-2")
    page = coord_disrupt.snapshot(everyone=True, run=_quiet)
    assert any(r["id"] == sent["id"] and r["reply"] == "yes" for r in page["handshakes"])
    assert "an agent is holding demo-proj (integration)" in page["blocking"]
