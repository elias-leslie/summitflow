"""Fast single-file type checks use the light lane instead of queueing behind heavy suites."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app.utils import heavy_work as guard
from cli.commands import check

_REAL_ADMISSION_STATE = guard.admission_state


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", tmp_path / "lane")
    monkeypatch.setattr(guard, "admission_state", lambda now=None: guard.Admission(True, "test"))
    monkeypatch.setattr(guard, "_spare_capacity", lambda: False)
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check, "_resolve_command", lambda binary, *_args, **_: [binary])
    (tmp_path / ".git" / "st").mkdir(parents=True)
    return tmp_path


def _store(root: Path) -> Path:
    return root / ".git" / "st" / "lane-measurements.json"


def _admitted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    admitted: list[str] = []

    def run(work: guard.HeavyWork, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        admitted.append(work.work_class)
        return subprocess.CompletedProcess(command, 0, "fixture complete", "")

    monkeypatch.setattr(guard.HeavyWork, "run", run)
    return admitted


FAST = {"execution_ms": 80.0, "max_rss_kb": 200_000}
SLOW = {"execution_ms": 9_000.0, "max_rss_kb": 200_000}
LARGE = {"execution_ms": 80.0, "max_rss_kb": 3 * 1024 * 1024}


@pytest.mark.parametrize(("name", "args", "stored", "expected"), [
    # Unmeasured scopes stay heavy until one run shows they are fast.
    ("types", ["app/one.py"], {}, "heavy"),
    ("types", ["app/one.py"], {"types:file": FAST}, "light"),
    ("types", ["app/one.py"], {"types:file": SLOW}, "heavy"),
    ("types", ["app/one.py"], {"types:file": LARGE}, "heavy"),
    # A fast single-file timing never speaks for a multi-file or whole-project run.
    ("types", ["app/one.py", "app/two.py"], {"types:file": FAST}, "heavy"),
    # Changed-only runs pass several paths: their own timing decides, else a fast whole-project run bounds them.
    ("types", ["app/one.py", "app/two.py"], {"types:files": FAST}, "light"),
    ("types", ["app/one.py", "app/two.py"], {"types:files": SLOW, "types:project": FAST}, "heavy"),
    ("types", ["app/one.py", "app/two.py"], {"types:project": FAST}, "light"),
    ("types", ["app/one.py"], {"types:project": FAST}, "light"),
    ("types", ["app/one.py", "app/two.py"], {"types:project": SLOW}, "heavy"),
    ("types", [], {"types:file": FAST}, "heavy"),
    ("types", [], {"types:project": FAST}, "light"),
    # tsc takes no paths: its whole-project timing decides.
    ("tsc", [], {"tsc:project": FAST}, "light"),
    ("tsc", [], {"tsc:project": SLOW}, "heavy"),
    # Flags are not paths.
    ("types", ["--output-format", "concise", "app/one.py"], {"types:file": FAST}, "heavy"),
    ("types", ["--quiet", "app/one.py"], {"types:file": FAST}, "light"),
    # pytest never joins the light lane, whatever was recorded.
    ("pytest", ["tests/test_one.py"], {"pytest": FAST}, "heavy"),
])
def test_type_check_lane_follows_measured_scope(
    project: Path, monkeypatch: pytest.MonkeyPatch, name: str, args: list[str], stored: dict, expected: str,
) -> None:
    if stored:
        _store(project).write_text(json.dumps(stored))
    admitted = _admitted(monkeypatch)
    monkeypatch.setattr(check, "_run_on_ci_runner", lambda *_args: None)
    check._run_tool(name, {"binary": "ty" if name == "types" else name}, args)
    assert admitted == [expected]


def test_single_file_run_records_its_own_scope_and_keeps_others(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(project).write_text(json.dumps({"vitest": FAST, "types:project": SLOW}))
    _admitted(monkeypatch)
    check._run_tool("types", {"binary": "ty"}, ["app/one.py"])
    values = json.loads(_store(project).read_text())
    assert values["types:file"]["execution_ms"] >= 0
    assert values["vitest"] == FAST and values["types:project"] == SLOW
    # Multi-file (changed-only) runs keep their own scope.
    check._run_tool("types", {"binary": "ty"}, ["app/one.py", "app/two.py"])
    assert set(json.loads(_store(project).read_text())) == {"vitest", "types:file", "types:files", "types:project"}


def test_fast_type_check_does_not_wait_behind_heavy_suite(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Timing demonstration: a held heavy lane delays the unmeasured run, not the measured one."""
    _admitted(monkeypatch)
    held, release = threading.Event(), threading.Event()

    def heavy_suite() -> None:
        with guard.heavy_work("check pytest", project="other"):
            held.set()
            release.wait(5)

    def timed(args: list[str]) -> float:
        capsys.readouterr()
        check._run_tool("types", {"binary": "ty"}, args)
        line = capsys.readouterr().out.splitlines()[-1]
        return float(line.split("|queue_ms:")[1].split("|")[0])

    _store(project).write_text(json.dumps({"types:file": FAST}))
    holder = threading.Thread(target=heavy_suite)
    holder.start()
    try:
        assert held.wait(5)
        assert timed(["app/one.py"]) < 250  # light lane: admitted at once
        threading.Timer(0.5, release.set).start()
        started = time.monotonic()
        heavy_queue_ms = timed(["app/one.py", "app/two.py"])  # heavy: queues until the suite ends
        assert heavy_queue_ms >= 400 and time.monotonic() - started >= 0.4
    finally:
        release.set()
        holder.join(5)


def test_project_lane_config_pins_class_and_sets_limits(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    admitted = _admitted(monkeypatch)
    monkeypatch.setattr(check, "_run_on_ci_runner", lambda *_args: None)
    _store(project).write_text(json.dumps({"types:file": SLOW}))
    (project / ".st-check.toml").write_text("[lanes.types]\nmax_execution_ms = 20000\n")
    check._run_tool("types", {"binary": "ty"}, ["app/one.py"])
    (project / ".st-check.toml").write_text('[lanes.types]\nclass = "heavy"\n')
    _store(project).write_text(json.dumps({"types:file": FAST}))
    check._run_tool("types", {"binary": "ty"}, ["app/one.py"])
    assert admitted == ["light", "heavy"]


def test_cleanroom_takes_light_class_only_after_a_cheap_identical_run(project: Path) -> None:
    from cli.lib import lane_measurements as lanes

    keys = lanes.cleanroom_keys(["python", "-c", "pass"])
    assert keys != lanes.cleanroom_keys(["python", "-c", "pass"], deps=True)
    assert lanes.admission_class(project, "cleanroom", keys) == "heavy"
    lanes.record(project, "cleanroom", keys, 900.0, 80_000)
    assert lanes.admission_class(project, "cleanroom", keys) == "light"
    lanes.record(project, "cleanroom", keys, 60_000.0, 80_000)
    assert lanes.admission_class(project, "cleanroom", keys) == "heavy"
    for index in range(60):
        lanes.record(project, "cleanroom", [f"cleanroom:{index}"], 1.0, 1)
    assert len([key for key in json.loads(_store(project).read_text()) if key.startswith("cleanroom:")]) == 50


def test_amber_gate_holds_heavy_but_not_measured_light(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Real admission path with a stubbed Nightshift file: amber closes heavy admission only."""
    gate = tmp_path / "admission.json"
    gate.write_text(json.dumps({"v": 1, "state": "amber", "admit": False, "reason": "Memory is tight",
                                "expires_at": time.time() + 600}))
    monkeypatch.setattr(guard, "NIGHTSHIFT_ADMISSION", gate)
    monkeypatch.setattr(guard, "admission_state", _REAL_ADMISSION_STATE)
    _admitted(monkeypatch)
    monkeypatch.setattr(check, "_run_on_ci_runner", lambda *_args: None)
    _store(project).write_text(json.dumps({"types:project": FAST}))
    started = time.monotonic()
    check._run_tool("types", {"binary": "ty"}, ["app/one.py", "app/two.py"])  # measured light: no gate
    assert time.monotonic() - started < 0.9
    finished = threading.Event()

    def unmeasured() -> None:
        with guard.heavy_work("check pytest", project="other"):
            finished.set()

    worker = threading.Thread(target=unmeasured, daemon=True)
    worker.start()
    assert not finished.wait(1.3)  # heavy still waits for host admission
    gate.write_text(json.dumps({"v": 1, "state": "green", "admit": True, "reason": "ok",
                                "expires_at": time.time() + 600}))
    assert finished.wait(5)
    worker.join(5)
