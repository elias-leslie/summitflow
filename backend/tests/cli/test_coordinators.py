"""Coordinator lineage from Tether in session listings and conflict hints."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cli.lib import coord, coord_lineage, coordinators, leases

COORD = {"id": "c0000001", "displayTitle": "Personal Workspace", "coordinator": True, "coordinatorId": None}
LANE = {"id": "a0000001", "displayTitle": "SummitFlow — st ownership output", "coordinator": False,
        "coordinatorId": "c0000001"}
ORPHAN = {"id": "a0000002", "displayTitle": " ", "label": "Session 3", "coordinator": False,
          "coordinatorId": "deadbeef"}


@pytest.fixture
def tether(monkeypatch, tmp_path):
    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path)
    coordinators.sessions.cache_clear()
    coordinators._harness_widgets.cache_clear()
    catalog = {d["id"]: d for d in (COORD, LANE, ORPHAN)}
    monkeypatch.setattr(coordinators, "sessions", lambda: catalog)
    monkeypatch.setattr(coordinators, "_harness_widgets", lambda: {"c0000001": [f"{os.getpid()}:1"]})
    coord_lineage.save_doc({"identities": {
        "cc:000old": {"anchor": f"{os.getpid()}:1", "last": "2026-10-13T10:00:00+00:00"},
        "cc:96eb15": {"anchor": f"{os.getpid()}:1", "last": "2026-10-13T12:00:00+00:00"},
    }})
    return catalog


def test_title_is_tethers_display_title():
    assert coordinators.title(COORD) == "Personal Workspace"  # Tether's wording, as it is
    assert coordinators.title(ORPHAN) == "Session 3"


def test_lane_belongs_to_coordinator_with_its_latest_agent_id(tether):
    assert coordinators.title(LANE) == "SummitFlow — st ownership output"
    assert coordinators.belongs_to("a0000001") == "belongs to Personal Workspace (cc:96eb15)"
    assert coordinators.belongs_to("c0000001") is None
    assert coordinators.belongs_to("a0000002") == "belongs to Coordinator"  # coordinator ended
    assert coordinators.session_suffix("c0000001") == " | Personal Workspace | coordinator"
    assert coordinators.session_suffix("a0000001") == (
        " | SummitFlow — st ownership output | belongs to Personal Workspace (cc:96eb15)")
    assert coordinators.session_suffix("ffffffff") == ""


def test_conflict_hint_names_the_holders_coordinator(tether, monkeypatch):
    monkeypatch.setattr(coordinators, "widget_for_anchor", lambda anchor: "a0000001" if anchor == "9:9" else None)
    lease = leases.Lease("l1", "cc:abcdef", "claude-code", "s", "claude_code", ["/r/a.py"], None,
                         "2026-10-13T12:00:00+00:00", "2026-10-13T12:00:00+00:00", anchor="9:9")
    line = coord.holder_line("summitflow", lease)
    assert line.endswith("; belongs to Personal Workspace (cc:96eb15); raise conflicts there")
    lease.anchor = "1:1"
    assert "belongs to" not in coord.holder_line("summitflow", lease)


def test_session_record_maps_to_its_tether_session():
    assert coordinators.widget_for_session({"tmux_session_name": "aico-afd26802"}) == "afd26802"
    assert coordinators.widget_for_session({"external_identity": {"aico_widget_id": "12345678"}}) == "12345678"
    assert coordinators.widget_for_session({"tmux_session_name": "main"}) is None
    assert coordinators.widget_for_session({"external_identity": {"aico_session_id": "aico-widget-cfa6ffb1"}}) == "cfa6ffb1"
    assert coordinators.widget_for_session({"external_identity": {"aico_session_id": "other"}}) is None


def test_tether_root_handle_yields_to_the_harness_identity(monkeypatch):
    monkeypatch.setenv("ST_SESSION_ID", "aico-root-4accb4c4-f49c-4a0b-a6be-cefd42a0d3ee")
    monkeypatch.setenv("ST_COORD_ANCHOR", "1:1")
    monkeypatch.setenv("ST_COORD_HARNESS", "claude_code")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "fb716ef9-4afc-4e55-b2c9-9d651051278d")
    assert leases.identify_agent()[0] == "cc:fb716e"
    assert leases.identify_agent(native=False)[0] == "st:aico-r"  # task-claim identity unchanged
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    assert leases.identify_agent()[0] == "st:4accb4"  # distinct per root, not the shared prefix
    monkeypatch.setenv("ST_SESSION_ID", "fleet-session-1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "fb716ef9-4afc-4e55-b2c9-9d651051278d")
    assert leases.identify_agent()[0] == "st:fleet-"  # explicit ST identities still win


def test_coordinator_without_a_session_record_is_listed(tether):
    (entry,) = coordinators.unrecorded_coordinators({"a0000001", None})
    assert entry["widget_id"] == "c0000001" and entry["agent_id"] == "cc:96eb15"
    assert coordinators.unrecorded_line(entry) == (
        "SES - | active | - | cc:96eb15 | task=- state=no-session-record | Personal Workspace | coordinator")
    assert coordinators.unrecorded_coordinators({"c0000001"}) == []


def test_widget_answers_with_the_newest_identity_on_any_of_its_harness_processes(monkeypatch, tmp_path):
    """A Claude Code session moved into a background job keeps its first process in the pane;
    the job is a second harness process in the same widget and carries the live identity."""
    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path)
    monkeypatch.setattr(coordinators, "_harness_widgets", lambda: {"w0000001": ["9611:1", "21914:2"]})
    coord_lineage.save_doc({"identities": {
        "cc:53c606": {"anchor": "9611:1", "last": "2026-10-30T22:17:00+00:00"},
        "cc:1c7a9f": {"anchor": "21914:2", "last": "2026-10-31T16:00:00+00:00"},
        "cc:other1": {"anchor": "7777:3", "last": "2026-10-31T17:00:00+00:00"},
    }})
    assert coordinators.agent_for_widget("w0000001") == "cc:1c7a9f"
    assert coordinators.agent_for_widget("w0000002") is None


def test_background_job_binary_is_a_claude_harness(monkeypatch):
    """A background job execs ~/.local/share/claude/versions/<version>, so its comm is the version."""
    monkeypatch.setattr(os, "readlink", lambda path: "/home/u/.local/share/claude/versions/2.1.314")
    assert coord_lineage.harness_provider(1234, "2.1.314") == "claude_code"
    assert coord_lineage.harness_provider(1234, "claude") == "claude_code"
    monkeypatch.setattr(os, "readlink", lambda path: "/usr/bin/python3.14")
    assert coord_lineage.harness_provider(1234, "python3") is None


@pytest.mark.parametrize(("args", "shared"), [
    ([], False),
    (["--bg-pty-host", "/tmp/x.sock"], True),
    (["--bg-spare", "/tmp/x.sock"], True),
    (["daemon", "run"], True),
    (["app-server"], True),
])
def test_shared_hosts_are_no_agent(args, shared):
    import subprocess
    import sys
    import time

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *args])
    try:
        for _ in range(100):  # the child's cmdline is ours until exec finishes
            if b"time.sleep" in Path(f"/proc/{proc.pid}/cmdline").read_bytes():
                break
            time.sleep(0.01)
        assert coord_lineage.shared_host(proc.pid) is shared
    finally:
        proc.kill()
        proc.wait()
