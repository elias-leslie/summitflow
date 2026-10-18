"""Memory notices for the coordination inbox hook (cli.lib.coord_memory): shown once, fail open, no false notices."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from cli.lib import coord_memory

PANE = "tmux-spawn-5d6d3cae-0097-477d-ae42-774fabec1fe8.scope"
OLD_PANE = "tmux-spawn-0f0f0f0f-0097-477d-ae42-774fabec1fe8.scope"


class Host:
    """A fake pane cgroup, memory event record, memctl heartbeat and `nightshift` executable."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.cgroup = tmp / "sys" / "user.slice" / "app.slice" / PANE
        self.cgroup.mkdir(parents=True)
        (tmp / "cgroup").write_text(f"0::/user.slice/app.slice/{PANE}\n")
        self.events = tmp / "memory-events.jsonl"
        self.heartbeat = tmp / "memctl.json"
        self.heartbeat.write_text("{}")
        self.out = tmp / "records.json"
        self.calls = tmp / "calls"
        exe = tmp / "nightshift"
        exe.write_text(f"#!/bin/sh\necho \"$@\" >> {self.calls}\ncat {self.out}\n")
        exe.chmod(0o755)
        self.records: list[dict] = []
        self.counter(0)
        self.write()

    def paths(self, nightshift: bool = True) -> coord_memory.Paths:
        return coord_memory.Paths(state_dir=self.tmp / "state", proc_cgroup=self.tmp / "cgroup",
                                  cgroup_root=self.tmp / "sys", events=self.events, heartbeat=self.heartbeat,
                                  nightshift=str(self.tmp / ("nightshift" if nightshift else "missing")))

    def counter(self, n: int) -> None:
        (self.cgroup / "memory.events").write_text(f"low 0\nhigh 0\nmax 0\noom 0\noom_kill {n}\noom_group_kill 0\n")

    def write(self) -> None:
        self.out.write_text(json.dumps(self.records))
        self.events.write_text("".join(json.dumps(r) + "\n" for r in self.records))  # size changes with each record

    def add(self, **rec) -> dict:
        full = {"v": 1, "kind": "kill", "killer": None, "scope": PANE, "tether_session_id": None, "pid": None,
                "starttime": None, "comm": None, "cmdline_head": None, "bytes": None, "class": "tool",
                "host_state": "red", **rec}
        self.records.append(full)
        self.write()
        return full

    def queries(self) -> int:
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0


def take(agent: str, host: Host, **kw) -> str | None:
    note = coord_memory.check(agent, paths=kw.pop("paths", None) or host.paths(), **kw)
    if note is None:
        return None
    note.done()
    return note.text


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def test_outside_an_agent_pane_is_silent_and_reads_nothing_else(host):
    (host.tmp / "cgroup").write_text("0::/user.slice/user-1000.slice/session-2.scope\n")
    host.add(ts=time.time(), killer="memctl", pid=10, comm="python")
    assert take("cc:aaaaaa", host) is None
    assert host.queries() == 0


def test_memctl_kill_is_told_once_then_quiet_without_asking_again(host):
    assert take("cc:aaaaaa", host) is None  # baseline
    host.add(ts=time.time(), killer="memctl", pid=4242, comm="python", cmdline_head="python -m pytest -n 8",
             bytes=3 * 2**30, members=5)
    text = take("cc:aaaaaa", host)
    assert text and "memctl killed python (pid 4242, `python -m pytest -n 8`), 3.0 GiB" in text
    assert "rest of its tool job (5 processes in all)" in text and "exit 137" in text
    asked = host.queries()
    assert take("cc:aaaaaa", host) is None
    assert host.queries() == asked  # nothing changed: no Nightshift call on the hot path


def test_tether_guard_kill_is_told_as_a_tool_job_kill_not_a_kernel_kill(host):
    """Since 2026-10-17 Tether's memory guard kills runaway tool jobs (killer tether); a counter-only notice from the
    same moment never silences it, because the guard's SIGKILL is not a kernel OOM kill."""
    assert take("cc:aaaaaa", host) is None
    now = time.time()
    host.add(ts=now, killer="tether", pid=4242, comm="python", bytes=3 * 2**30, members=2)
    host.counter(1)  # an unrelated kernel kill in the same pane, same moment
    text = take("cc:aaaaaa", host, now=now)
    assert text and "Tether's memory guard killed python (pid 4242), 3.0 GiB" in text
    assert "rest of its tool job (2 processes in all)" in text and "critically low on memory" in text


def test_kernel_kill_counter_tells_at_once_and_the_later_record_stays_quiet(host):
    assert take("cc:aaaaaa", host) is None
    now = time.time()
    host.counter(1)
    text = take("cc:aaaaaa", host, now=now)
    assert text and "the kernel killed 1 process in this pane" in text and "nightshift memory events --mine" in text
    # memctl writes the journal-detailed record on its next tick, with the kill's own time
    host.add(ts=now - 0.2, killer="kernel-pane-cap", pid=77, comm="python3", bytes=300 * 2**20)
    assert take("cc:aaaaaa", host, now=now + 12) is None
    # and a counter-only record from its tick just after is the same kill
    host.add(ts=now + 9, killer="kernel-pane-cap", count=1, source="counter")
    assert take("cc:aaaaaa", host, now=now + 40) is None


def test_kernel_kill_already_recorded_gives_the_detailed_line_only(host):
    assert take("cc:aaaaaa", host) is None
    host.add(ts=time.time(), killer="kernel-pane-cap", pid=77, comm="python3", bytes=300 * 2**20)
    host.counter(1)
    text = take("cc:aaaaaa", host)
    assert text and "the kernel killed python3 (pid 77), 300 MiB; this pane reached its memory limit." in text
    assert "in this pane for memory" not in text


def test_counter_only_notice_without_memctl_points_at_the_kernel_log(host):
    host.heartbeat.unlink()
    assert take("cc:aaaaaa", host, paths=host.paths(nightshift=False)) is None
    host.counter(2)
    text = take("cc:aaaaaa", host, paths=host.paths(nightshift=False))
    assert text and "killed 2 processes in this pane" in text and "journalctl -k --since" in text
    assert take("cc:aaaaaa", host, paths=host.paths(nightshift=False)) is None


def test_each_subagent_and_the_parent_hear_once(host):
    for agent in ("cc:aaaaaa", "cc:aaaaaa/sub1", "cc:aaaaaa/sub2"):
        assert take(agent, host) is None
    host.add(ts=time.time(), killer="memctl", pid=5, comm="node")
    for agent in ("cc:aaaaaa", "cc:aaaaaa/sub1", "cc:aaaaaa/sub2"):
        assert take(agent, host) is not None
        assert take(agent, host) is None


def test_a_new_agent_hears_nothing_from_before_it_and_a_resumed_one_the_last_day(host):
    host.add(ts=time.time() - 3 * 3600, killer="kernel-pane-cap", pid=9, comm="claude", scope=OLD_PANE,
             tether_session_id="236eb8e2", **{"class": "agent"})
    host.add(ts=time.time() - 3 * 3600 + 1, kind="pane-stopped", killer="kernel-pane-cap", scope=OLD_PANE,
             agent="claude", **{"class": "container"})
    host.add(ts=time.time() - 60, killer="kernel-pane-cap", pid=12, comm="python3")
    assert take("cc:bbbbbb", host) is None  # a new session or subagent: an earlier kill is not its news
    assert host.queries() == 0
    text = take("cc:cccccc", host, resumed=True)
    assert text and "the kernel killed this session's agent, claude (pid 9); the pane this session ran in before " \
        "reached its memory limit." in text
    assert "the pane this session ran in before stopped as a whole" in text
    assert take("cc:cccccc", host, resumed=True) is None


def test_subagent_started_after_a_kill_hears_only_its_own(host):
    now = time.time()
    assert take("cc:aaaaaa", host, now=now - 90) is None
    host.counter(1)
    assert "killed 1 process" in (take("cc:aaaaaa", host, now=now - 85) or "")
    host.add(ts=now - 85, killer="kernel-pane-cap", pid=7, comm="python3")  # the parent's earlier kill, recorded
    assert take("cc:aaaaaa/sub", host, now=now - 5) is None  # SubagentStart: the baseline
    host.counter(2)  # its first tool call is killed; memctl has not written the record yet
    text = take("cc:aaaaaa/sub", host, now=now)
    assert text and "killed 1 process in this pane" in text and "pid 7" not in text


def test_warning_and_agent_hog_are_told_outside_hog_never(host):
    assert take("cc:aaaaaa", host) is None
    host.add(ts=time.time(), kind="outside-hog", scope="app-com.google.Chrome-1.scope", bytes=9 * 2**30,
             **{"class": "container"})
    assert take("cc:aaaaaa", host) is None
    host.add(ts=time.time(), kind="warning", pid=31, comm="python", bytes=6 * 2**30)
    host.add(ts=time.time(), kind="agent-hog", pid=8, comm="claude", bytes=9 * 2**30, **{"class": "agent"})
    text = take("cc:aaaaaa", host)
    assert text and "growing fastest: python (pid 31) uses 6.0 GiB" in text
    assert "this pane's agent, claude (pid 8) is the biggest user (9.0 GiB)" in text
    assert "exit 137" not in text  # nothing was killed


def test_a_burst_of_kills_stays_short(host):
    assert take("cc:aaaaaa", host, now=time.time() - 20) is None
    for i in range(9):
        host.records.append({"v": 1, "kind": "kill", "killer": "memctl", "scope": PANE, "pid": 100 + i,
                             "comm": "python", "ts": time.time() - 9 + i, "class": "tool"})
    host.write()
    text = take("cc:aaaaaa", host) or ""
    assert "4 earlier events" in text and "pid 108" in text and "pid 103" not in text


def test_undelivered_notice_comes_back(host):
    assert take("cc:aaaaaa", host) is None
    host.add(ts=time.time(), killer="memctl", pid=4, comm="cargo")
    note = coord_memory.check("cc:aaaaaa", paths=host.paths())
    assert note is not None
    note.done(delivered=False)
    assert take("cc:aaaaaa", host) is not None


def test_broken_nightshift_or_state_never_raises(host):
    assert take("cc:aaaaaa", host) is None
    (host.tmp / "nightshift").write_text("#!/bin/sh\necho not json; exit 3\n")
    host.add(ts=time.time(), killer="memctl", pid=4, comm="cargo")
    assert take("cc:aaaaaa", host) is None  # Nightshift unavailable: no record notice
    (host.tmp / "state" / "mem-cc_aaaaaa.json").write_text("{broken")
    host.counter(1)
    assert take("cc:aaaaaa", host) is None  # unreadable state is a fresh baseline, not a guess
    (host.cgroup / "memory.events").unlink()
    assert take("cc:aaaaaa", host) is None


def test_hot_path_is_cheap(host):
    assert take("cc:aaaaaa", host) is None
    start = time.perf_counter()
    for _ in range(200):
        assert coord_memory.check("cc:aaaaaa", paths=host.paths()) is None
    assert (time.perf_counter() - start) / 200 < 0.005
    assert os.path.exists(host.tmp / "state" / "mem-cc_aaaaaa.json")
