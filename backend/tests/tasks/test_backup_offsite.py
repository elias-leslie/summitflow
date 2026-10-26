"""The daily Google Drive job: restic reads the btrbk snapshots at their real paths, with no staging."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.tasks import backup_offsite as offsite
from app.tasks import backup_overview as overview
from app.tasks.backup_proc import run_process

NOW = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)  # 23:00 the evening before, New York time
POINTS = [
    {"source": "/", "snapshot": "/.btrbk/root.20261026T023015-0400"},
    {"source": "/home", "snapshot": "/home/.btrbk/home.20261026T023015-0400"},
    {"source": "/srv/workspaces", "snapshot": "/srv/workspaces/.btrbk/workspaces.20261026T023015-0400"},
    {"source": "/var/lib/docker", "snapshot": "/var/lib/docker/.btrbk/docker.20261026T023015-0400"},
]


def test_snapshots_are_mounted_over_their_real_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(offsite, "project_tags", lambda: ["project:aico"])
    jobs = {job.name: job for job in offsite.subvolume_jobs(POINTS, "run-1")}
    assert set(jobs) == {"workspaces", "home", "root"}  # docker, models and logs stay local-only
    assert jobs["workspaces"].binds == (("/srv/workspaces/.btrbk/workspaces.20261026T023015-0400", "/srv/workspaces"),)
    assert ("/.btrbk/root.20261026T023015-0400/etc", "/etc") in jobs["root"].binds
    assert "project:aico" in jobs["workspaces"].tags and "btrbk:run-1" in jobs["workspaces"].tags


def test_a_missing_snapshot_fails_the_day_instead_of_backing_up_less() -> None:
    with pytest.raises(offsite.OffsiteError, match="/home"):
        offsite.subvolume_jobs([POINTS[0], POINTS[2]], "run-1")


def test_root_runs_in_a_private_mount_namespace_with_a_clean_environment() -> None:
    command = offsite._as_root(["/bin/restic", "backup"], {"PATH": "/bin", "RCLONE_CONFIG": "/run/x"}, [("/snap", "/real")])
    assert command[:6] == ["sudo", "-n", "unshare", "--mount", "--propagation", "private"]
    assert "env" in command and "-i" in command and "RCLONE_CONFIG=/run/x" in command
    assert command[command.index("--", 8) - 2 :][:3] == ["/snap", "/real", "--"]
    assert command[-2:] == ["/bin/restic", "backup"]


def test_only_old_per_source_snapshots_age_out() -> None:
    snapshots = [
        {"id": "old-legacy", "time": "2026-09-20T10:00:00-04:00", "tags": ["source:aico"]},
        {"id": "new-legacy", "time": "2026-10-20T10:00:00-04:00", "tags": ["source:aico"]},
        {"id": "old-daily", "time": "2026-09-01T10:00:00-04:00", "tags": ["offsite", "job:workspaces"]},
        {"id": "untagged", "time": "2026-09-01T10:00:00-04:00", "tags": []},
    ]
    assert offsite.retention_ids(snapshots, now=NOW, legacy_days=30) == ["old-legacy"]


@pytest.mark.parametrize(
    ("last_success", "hour", "expected"),
    [
        (None, 2, "daily"),                                  # first ever run inside the window
        ("2026-10-26T06:00:00+00:00", 2, None),               # already done today (local date)
        ("2026-10-25T07:00:00+00:00", 7, None),               # outside the window, done 24 h ago
        ("2026-10-24T20:00:00+00:00", 7, "catch-up"),         # a day was missed: do not wait for the window
    ],
)
def test_the_drive_copy_runs_once_a_day_and_catches_up(monkeypatch: pytest.MonkeyPatch, last_success: str | None, hour: int, expected: str | None) -> None:
    monkeypatch.setattr(offsite, "get_settings", lambda: SimpleNamespace(backup_schedule_window="02:00-06:00", backup_schedule_timezone="America/New_York"))
    now = datetime(2026, 10, 26, hour + 4, 30, tzinfo=UTC)  # New York is UTC-4
    state = {"last_success_at": last_success} if last_success else {}
    assert offsite.offsite_due(state, now) == expected
    assert offsite.offsite_due(state, now, force=True) == "requested"


def test_a_failed_attempt_is_not_retried_in_a_storm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(offsite, "get_settings", lambda: SimpleNamespace(backup_schedule_window=None, backup_schedule_timezone="America/New_York"))
    state = {"last_attempt_at": (NOW - timedelta(hours=1)).isoformat(), "last_status": "failed"}
    assert offsite.offsite_due(state, NOW) is None
    assert offsite.offsite_due({**state, "last_attempt_at": (NOW - timedelta(hours=4)).isoformat()}, NOW) == "daily"


def test_run_process_stops_a_hung_command_at_the_deadline() -> None:
    result = run_process([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGINT, signal.SIG_DFL); time.sleep(60)"], env=None, timeout=0.5)
    assert result.returncode == 124 and "timed out" in result.stderr


def test_run_process_reads_the_restic_summary_and_keeps_output_in_memory() -> None:
    script = "import json; print(json.dumps({'message_type': 'status'})); print(json.dumps({'message_type': 'summary', 'snapshot_id': 'abc', 'total_files_processed': 3}))"
    result = run_process([sys.executable, "-c", script], env=None, timeout=20)
    assert result.ok and result.summary["snapshot_id"] == "abc" and result.stdout == ""


def test_restic_exit_3_with_a_snapshot_is_a_warning_not_a_failure() -> None:
    script = "import json, sys; print(json.dumps({'message_type': 'summary', 'snapshot_id': 'abc'})); sys.exit(3)"
    assert run_process([sys.executable, "-c", script], env=None, timeout=20).ok


class FakeRepo:
    def __init__(self, result: Any) -> None:
        self.target = SimpleNamespace(hostname="host")
        self.runtime = SimpleNamespace(excludes=Path("/run/excludes"))
        self.result = result
        self.calls: list[tuple[Any, ...]] = []

    def restic(self, *args: str, **kwargs: Any) -> Any:
        self.calls.append(args)
        return self.result


def test_a_database_dump_that_streams_nothing_is_not_a_recovery_point() -> None:
    result = offsite.Result(0, {"snapshot_id": "abc", "total_bytes_processed": 0})
    job = offsite.Job(name="postgres", kind="stream", tags=("offsite",), required=True, command=("pg_dumpall",), filename="postgres-dumpall.sql")
    record = offsite.run_job(FakeRepo(result), job)  # type: ignore[arg-type]
    assert record["status"] == "failed" and "no data" in record["error"]


def test_a_job_record_keeps_what_the_ui_and_receipts_need() -> None:
    result = offsite.Result(0, {"snapshot_id": "abc", "total_files_processed": 5, "total_bytes_processed": 10, "data_added": 4, "files_new": 1, "files_changed": 2})
    job = offsite.Job(name="home", kind="subvolume", tags=("offsite", "project:aico"), required=True, binds=(("/s", "/home"),), paths=("/home",))
    record = offsite.run_job(FakeRepo(result), job)  # type: ignore[arg-type]
    assert record["status"] == "ok" and record["snapshot_id"] == "abc" and "project:aico" not in record["tags"]
    assert record["added_bytes"] == 4 and record["changed_files"] == 2


def test_a_powered_off_guest_is_not_a_failure() -> None:
    record = offsite.run_job(FakeRepo(None), offsite.Job(name="pve-vm", kind="offline", tags=(), required=False))  # type: ignore[arg-type]
    assert record["status"] == "offline"


def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **values: Any) -> None:
    monkeypatch.setattr(offsite, "state_dir", lambda: tmp_path)
    (tmp_path / "state.json").write_text(json.dumps(values))


def test_health_is_quiet_while_both_layers_are_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _state(tmp_path, monkeypatch, last_success_at=(NOW - timedelta(hours=20)).isoformat(), last_status="ok", check={"failures": 1})
    monkeypatch.setattr(overview, "local_summary", lambda **_: {"enabled": True, "last_good_at": (NOW - timedelta(hours=3)).isoformat(), "last_run": {"status": "failed", "error": "slow"}})
    assert overview.health_problems(NOW) == []  # one failed run and one failed check are not problems


def test_health_reports_only_missing_recovery_points(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _state(tmp_path, monkeypatch, last_success_at=(NOW - timedelta(hours=49)).isoformat(), last_error="Drive unreachable",
           check={"failures": 3, "error": "boom"}, spot_restore={"status": "failed", "error": "mismatch"})
    monkeypatch.setattr(overview, "local_summary", lambda **_: {"enabled": True, "last_good_at": (NOW - timedelta(hours=30)).isoformat(), "last_run": None})
    keys = {problem["key"] for problem in overview.health_problems(NOW)}
    assert keys == {"local-missing", "offsite-missing", "offsite-check", "offsite-spot-restore"}


def test_health_waits_two_days_before_calling_a_first_run_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _state(tmp_path, monkeypatch, first_attempt_at=(NOW - timedelta(hours=10)).isoformat())
    monkeypatch.setattr(overview, "local_summary", lambda **_: {"enabled": False, "last_good_at": None, "last_run": None})
    assert overview.health_problems(NOW) == []


def test_the_sources_receipt_does_not_call_a_first_seed_failing_until_its_window_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overview, "local_summary", lambda **_: {"enabled": True, "last_good_at": NOW.isoformat(), "last_run": {"status": "completed"}})
    _state(tmp_path, monkeypatch, last_status="running", first_attempt_at=(NOW - timedelta(hours=10)).isoformat())
    assert overview.freshness_sources(NOW)["offsite-restic"]["ok"] is True
    _state(tmp_path, monkeypatch, last_status="failed", first_attempt_at=(NOW - timedelta(hours=60)).isoformat())
    assert overview.freshness_sources(NOW)["offsite-restic"]["ok"] is False


def test_stale_run_marker_is_cleared_at_the_start_of_the_next_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _state(tmp_path, monkeypatch, last_status="running", current_run={"started_at": "x"})
    state = offsite.recover_state()
    assert state["last_status"] == "failed" and "current_run" not in state and "redone" in state["last_error"]


def test_the_caches_live_on_scratch_and_are_dropped_when_they_outgrow_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = offsite.Runtime(tmp_path / "run", tmp_path / "scratch")
    calls: list[list[str]] = []
    monkeypatch.setattr(offsite, "_tree_bytes", lambda _: 3 * 1024**2)
    monkeypatch.setattr(offsite.subprocess, "run", lambda command, **_: calls.append(command) or SimpleNamespace(returncode=0))
    assert offsite.trim_runtime(runtime, cap=1024**3) == 6 * 1024**2
    assert [command[command.index("--") + 1 :] for command in calls] == [[str(runtime.tmp)]]  # under the cap: only the spool goes
    calls.clear()
    monkeypatch.setattr(offsite, "_tree_bytes", lambda _: 5 * 1024**3)
    assert offsite.trim_runtime(runtime, cap=1024**3) == 10 * 1024**3
    assert [command[command.index("--") + 1 :] for command in calls] == [[str(runtime.tmp)], [str(runtime.root_cache), str(runtime.cache)]]
    assert str(runtime.cache).startswith(str(tmp_path / "scratch")) and str(runtime.tmp).startswith(str(tmp_path / "run"))


def test_freshness_marks_the_drive_job_and_the_host_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _state(tmp_path, monkeypatch, last_success_at=(NOW - timedelta(hours=5)).isoformat(), last_status="ok",
           jobs={"workspaces": {"time": NOW.isoformat()}, "pve-host-files": {"time": (NOW - timedelta(hours=60)).isoformat()}})
    monkeypatch.setattr(overview, "local_summary", lambda **_: {"enabled": True, "last_good_at": (NOW - timedelta(hours=2)).isoformat(), "last_run": {"status": "completed"}})
    sources = overview.freshness_sources(NOW)
    assert sources["host-btrbk"]["ok"] and sources["offsite-restic"]["ok"] and sources["offsite-restic"]["frequency"] == "daily"
    assert sources["pve-host-files"]["ok"] is False and "workspaces" not in sources
    assert overview.offsite_runs({"repository": "rclone:summitflow-drive:SummitFlow-Restic"})["remote"] == "summitflow-drive"


def test_the_redis_dump_goes_through_a_temporary_file_because_a_pipe_fails_redis_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.backup_database import redis_dump_invocation

    monkeypatch.setenv("REDIS_PASSWORD", "fixture-secret")
    command, env = redis_dump_invocation()
    assert command[:2] == ["sh", "-c"] and "/dev/stdout" not in " ".join(command) and "fixture-secret" not in " ".join(command)
    assert env["REDISCLI_AUTH"] == "fixture-secret"


def test_a_snapshot_listing_is_read_whole_not_as_a_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def fake_run(command: Any, *, env: Any, timeout: float, capture: bool = False, **_: Any) -> Any:
        seen.append(capture)
        return offsite.Result(0, {}, json.dumps([{"id": "x" * 5000}]))

    monkeypatch.setattr(offsite, "run_process", fake_run)
    monkeypatch.setattr(offsite, "_restic_args", lambda *a, **k: ["restic"])
    monkeypatch.setattr(offsite, "_env", lambda *a, **k: {"PATH": "/usr/bin"})
    assert offsite.Repo(SimpleNamespace(), SimpleNamespace()).json("snapshots")[0]["id"] == "x" * 5000  # type: ignore[arg-type]
    assert seen == [True]


def test_the_spot_restore_picks_small_top_level_files_of_a_project() -> None:
    lines = [{"type": "dir", "path": "/w/p"}, {"type": "file", "path": "/w/p/a.md", "size": 10}, {"type": "file", "path": "/w/p/big.bin", "size": 10**9},
             {"type": "file", "path": "/w/p/sub/b.md", "size": 10}, {"type": "file", "path": "/w/p/empty", "size": 0}]
    repo = FakeRepo(offsite.Result(0, {}, "\n".join(json.dumps(line) for line in lines)))
    assert offsite._small_files(repo, "snap", "/w/p") == ["/w/p/a.md"]  # type: ignore[arg-type]
    assert repo.calls[0][:2] == ("ls", "--json")


def test_a_leftover_runtime_config_never_stops_the_next_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("ST_SCRATCH_ROOT", str(tmp_path / "scratch"))
    source = tmp_path / "rclone.conf"
    source.write_text("[summitflow-drive]\n")
    target = offsite.Target("b", "rclone:summitflow-drive:r", tmp_path / "pw", source, tmp_path, "host", True)
    first = offsite.prepare_runtime(target)
    first.rclone.chmod(0o400)  # as a root-run rclone leaves it: not writable by the next run
    again = offsite.prepare_runtime(target)
    assert again.rclone.read_text() == "[summitflow-drive]\n" and again.excludes.is_file()


@pytest.mark.parametrize(("some", "full", "starts"), [("2.37", "2.33", True), ("0.10", "0.10", True), ("30.00", "1.00", False), ("5.00", "12.00", False)])
def test_the_timer_waits_only_when_memory_pressure_is_really_high(tmp_path: Path, some: str, full: str, starts: bool) -> None:
    unit = (Path(__file__).resolve().parents[3] / "scripts/systemd/summitflow-host-backup.service").read_text()
    program = next(line for line in unit.splitlines() if line.startswith("ExecCondition=")).split("'\\''")[1]
    pressure = tmp_path / "memory"
    pressure.write_text(f"some avg10=1.00 avg60={some} avg300=0.00 total=1\nfull avg10=1.00 avg60={full} avg300=0.00 total=1\n")
    assert (subprocess.run(["awk", program, str(pressure)], check=False).returncode == 0) is starts  # numeric, not string, comparison


def test_only_backups_and_listings_use_the_persistent_cache() -> None:
    target = offsite.Target("b", "rclone:summitflow-drive:r", Path("/pw"), None, Path("/k"), "host", True)
    runtime = offsite.Runtime(Path("/run/x"), Path("/scratch/x"))
    for command in ("check", "prune", "restore", "dump"):
        arguments = offsite._restic_args(target, runtime, command, "--json")
        assert "--no-cache" in arguments and "--cache-dir" not in arguments
    for command in ("backup", "snapshots", "forget", "ls"):
        arguments = offsite._restic_args(target, runtime, command)
        assert arguments[arguments.index("--cache-dir") + 1] == str(runtime.cache) and "--no-cache" not in arguments


def test_a_project_restore_uses_the_path_the_snapshot_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import backup_offsite_restore as restore

    repo = FakeRepo(offsite.Result(0, {}))
    monkeypatch.setattr(restore, "open_repo", lambda: repo)
    monkeypatch.setattr(restore, "snapshots", lambda *_a, **_k: [{"id": "abc", "full_id": "abc" * 21 + "d", "time": "2026-10-26T00:00:00+00:00", "paths": ["/srv/workspaces"]}])
    result = restore.restore("demo", tmp_path / "out", dry_run=True)
    assert result["path"] == "/srv/workspaces/projects/demo"
