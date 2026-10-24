"""Startup system brief: who is told what, once per window, and silence when all is clear."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cli.lib import coord, startup_brief

FIXTURE = Path(__file__).parent / "fixtures/startup_brief/status-2026-10-24.json"
NOW = datetime(2026, 10, 24, 14, 20, tzinfo=UTC)


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A summitflow checkout, a ledger and a Nightshift status file, all private to the test."""
    repo = tmp_path / "summitflow"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    state = tmp_path / "services"
    for project in ("summitflow", "ominull", "neri"):
        (state / "projects" / project / "receipts").mkdir(parents=True)
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(state))
    monkeypatch.delenv("AICO_WIDGET_ID", raising=False)
    monkeypatch.setattr(coord, "project_for_path", lambda path: ("summitflow", repo))
    status = tmp_path / "status.json"
    status.write_text(FIXTURE.read_text())
    config = tmp_path / "brief.json"

    def configure(**values):
        config.write_text(json.dumps({"enabled": True, "ledger": str(tmp_path / "ledger.json"),
                                      "nightshift_status": str(status), **values}))

    configure()
    monkeypatch.setenv("ST_STARTUP_BRIEF_CONFIG", str(config))
    monkeypatch.setattr(startup_brief, "publication_item", lambda project, cfg, now: None)
    monkeypatch.setattr(startup_brief, "deploys_remotely", lambda project: False)
    return {"repo": repo, "state": state, "status": status, "configure": configure}


def _start(role, monkeypatch, *, now=NOW, **payload):
    monkeypatch.setattr(startup_brief, "session_role", lambda _payload: role)
    return startup_brief.brief({"cwd": "/x", **payload}, now=now)


def _status(host, findings):
    doc = json.loads(host["status"].read_text())
    doc["findings"] = findings
    host["status"].write_text(json.dumps(doc))


def test_fixture_replay_names_the_three_real_breakages(host, monkeypatch):
    text = "\n".join(_start("agent", monkeypatch))
    # Autosnap silently skipping every project since Oct 19.
    assert "autosnap point is 4d13h old" in text and "summitflow:" in text
    # Failing neri-evidence backup source, owned by SummitFlow's backups.
    assert "neri-evidence" in text
    # Reboot coordination held since Oct 22: the age and "stuck" say it is not progressing.
    assert "Reboot required. (open 1d16h since Oct 22, stuck)" in text
    assert "Tether snapshots sessions" not in text  # routing tail dropped


def test_second_session_in_window_is_silent_and_window_reshows(host, monkeypatch):
    host["configure"](nightshift_status_max_age_minutes=10_000)  # replaying one status file over a day
    first = _start("agent", monkeypatch)
    assert len(first) == 4  # header + three items
    assert _start("agent", monkeypatch, now=NOW + timedelta(hours=2)) == []
    later = _start("agent", monkeypatch, now=NOW + timedelta(hours=25))
    assert [line.split(" (open")[0] for line in later] == [line.split(" (open")[0] for line in first]


def test_a_new_episode_of_a_known_finding_is_shown_again(host, monkeypatch):
    _start("agent", monkeypatch)
    doc = json.loads(host["status"].read_text())
    for finding in doc["findings"]:
        if finding["code"] == "ws.reboot.required":
            finding["first_seen"] = "2026-10-24T14:00:00+00:00"
    host["status"].write_text(json.dumps(doc))
    again = _start("agent", monkeypatch, now=NOW + timedelta(minutes=5))
    assert len(again) == 2 and "Reboot required. (open 25m)" in again[1]


def test_project_items_reach_the_first_agent_in_each_project_once(host, monkeypatch):
    _start("agent", monkeypatch)
    monkeypatch.setattr(coord, "project_for_path", lambda path: ("neri", host["repo"]))
    neri = _start("agent", monkeypatch, now=NOW + timedelta(minutes=1))
    assert neri == []  # host items already shown to agents; neri owns none of the findings


def test_coordinator_sees_host_items_first_and_every_project(host, monkeypatch):
    (host["state"] / "projects/ominull/receipts/b1.json").write_text(json.dumps(
        {"build_id": "b1", "completed_at": NOW.timestamp() - 3600, "failed_phase": "restart_health",
         "previous_usable_release": None, "state": "failed"}))
    lines = _start("coordinator", monkeypatch)
    assert lines[1].startswith("- WARN host: davion-sidarli: Reboot required")
    assert any(line.startswith("- CRIT ominull: last deploy failed at restart_health 1h ago") for line in lines)
    # Coordinator views do not use up a project's first-entry brief.
    assert len(_start("agent", monkeypatch)) == 4


def test_failed_local_receipt_is_silent_for_a_project_deployed_in_a_guest(host, monkeypatch):
    (host["state"] / "projects/ominull/receipts/b1.json").write_text(json.dumps(
        {"build_id": "b1", "completed_at": NOW.timestamp() - 3600, "failed_phase": "restart_health",
         "previous_usable_release": None, "state": "failed"}))
    monkeypatch.setattr(startup_brief, "deploys_remotely", lambda project: project == "ominull")
    assert not any("last deploy failed" in line for line in _start("coordinator", monkeypatch))


def test_lane_gets_only_its_projects_blocking_items(host, monkeypatch):
    lines = _start("lane", monkeypatch)
    assert [line.split(":")[0] for line in lines[1:]] == ["- CRIT summitflow", "- CRIT summitflow"]
    assert not any("Reboot" in line for line in lines)


def test_native_subagent_gets_nothing(host, monkeypatch):
    assert startup_brief.brief({"cwd": "/x", "agent_id": "worker-1"}, now=NOW) == []
    assert startup_brief.brief({"cwd": "/x", "hook_event_name": "SubagentStart"}, now=NOW) == []


def test_all_clear_is_silent(host, monkeypatch):
    _status(host, [f for f in json.loads(FIXTURE.read_text())["findings"] if f["severity"] == "ok"])
    assert _start("coordinator", monkeypatch) == []


def test_line_budget_and_overflow_stays_new(host, monkeypatch):
    base = json.loads(FIXTURE.read_text())["findings"][1]
    _status(host, [{**base, "key": f"k{i}", "first_seen": NOW.isoformat()} for i in range(20)])
    host["configure"](max_lines=5)
    lines = _start("agent", monkeypatch)
    assert len(lines) == 5 and lines[-1] == "- +17 more: st pulse --brief"
    assert len(_start("agent", monkeypatch)) == 5  # the 17 cut items were never marked shown


def test_failed_acceptance_is_reported_after_the_quiet_period(host, monkeypatch):
    _status(host, [])
    acceptance = host["repo"] / ".git/st/acceptance"
    acceptance.mkdir(parents=True)
    record = {"acceptance_id": "a1", "state": "failed", "reason": "acceptance_checks_failed",
              "completed_at": (NOW - timedelta(minutes=10)).isoformat(), "source": {"commit": "0123456789abc"}}
    (acceptance / "a1.json").write_text(json.dumps(record))
    assert _start("lane", monkeypatch) == []  # likely being fixed right now
    record["completed_at"] = (NOW - timedelta(hours=3)).isoformat()
    (acceptance / "a1.json").write_text(json.dumps(record))
    lines = _start("lane", monkeypatch)
    assert lines[1] == ("- WARN summitflow: newest acceptance (0123456789) failed 3h ago: acceptance_checks_failed")


def test_stale_or_missing_nightshift_status_is_one_host_line(host, monkeypatch):
    host["status"].unlink()
    lines = _start("agent", monkeypatch)
    assert len(lines) == 2 and "Nightshift status unreadable" in lines[1]
    host["status"].write_text(json.dumps({"generated_at": (NOW - timedelta(hours=3)).isoformat(), "findings": []}))
    assert "Nightshift status is 3h old" in _start("coordinator", monkeypatch)[1]


def test_owner_only_items_are_tagged(host, monkeypatch):
    base = json.loads(FIXTURE.read_text())["findings"][1]
    _status(host, [{**base, "key": "sudo", "message": "sudo touched /etc/sudoers.",
                    "details": {"owner": "owner (rule 3: auth config)"}}])
    assert _start("agent", monkeypatch)[1].endswith("[owner's call]")


def test_hook_never_raises_and_stays_silent_on_failure(host, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("ledger disk full")

    monkeypatch.setattr(startup_brief, "brief", broken)
    assert startup_brief.hook_lines({"cwd": "/x"}) == []


def test_role_from_tether_descriptor(monkeypatch):
    from cli.lib import coordinators

    sessions = {"c1": {"id": "c1", "coordinator": True}, "l1": {"id": "l1", "coordinatorId": "c1"}, "s1": {"id": "s1"}}
    monkeypatch.setattr(coordinators, "sessions", lambda: sessions)
    roles = {}
    for widget in ("c1", "l1", "s1"):
        monkeypatch.setenv("AICO_WIDGET_ID", widget)
        roles[widget] = startup_brief.session_role({})
    monkeypatch.delenv("AICO_WIDGET_ID")
    assert roles == {"c1": "coordinator", "l1": "lane", "s1": "agent"}
    assert startup_brief.session_role({}) == "agent"
