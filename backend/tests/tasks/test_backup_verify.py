"""The weekly Drive read-back: bounded, never on the backup's path, and "out of time" is not a failure."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.tasks import backup_offsite as offsite
from app.tasks import backup_overview as overview
from app.tasks import backup_verify as verify

UNITS = Path(__file__).resolve().parents[3] / "scripts/systemd"


class Repo:
    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.runtime = SimpleNamespace(root=Path("/nonexistent"), cache=Path("/tmp"))

    def restic(self, *args: str, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.results.pop(0)


def _result(code: int, stdout: str = "", stderr: str = "") -> offsite.Result:
    return offsite.Result(code, {}, stdout, stderr)


def test_the_check_reads_a_byte_sized_sample_within_its_bound() -> None:
    repo = Repo(_result(0))
    record = verify.run_check(repo, {"failures": 1, "last_ok_at": "old"})  # type: ignore[arg-type]
    args, kwargs = repo.calls[0]
    assert args == ("check", "--read-data-subset=500M") and kwargs["timeout"] == verify.CHECK_BOUND_SECONDS <= 20 * 60
    assert record["status"] == "ok" and record["failures"] == 0 and record["last_ok_at"] != "old"


def test_a_check_that_runs_out_of_time_is_partial_and_changes_nothing_else() -> None:
    record = verify.run_check(Repo(_result(124, stderr="timed out after 900s")), {"failures": 1, "last_ok_at": "old"})  # type: ignore[arg-type]
    assert record["status"] == "partial" and record["failures"] == 1 and record["last_ok_at"] == "old" and "error" not in record


def test_a_check_that_finds_a_problem_counts_a_failure() -> None:
    record = verify.run_check(Repo(_result(1, stderr="pack abc: ciphertext verification failed")), {"failures": 1})  # type: ignore[arg-type]
    assert record["status"] == "failed" and record["failures"] == 2 and "ciphertext" in record["error"]


def test_partial_results_never_raise_a_health_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 10, 26, 12, tzinfo=UTC)
    monkeypatch.setattr(offsite, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(overview, "local_summary", lambda **_: {"enabled": False})
    (tmp_path / "state.json").write_text(json.dumps({"last_success_at": now.isoformat()}))
    offsite.update_verify(check={"status": "partial", "failures": 0}, spot_restore={"status": "partial", "failures": 0},
                          maintenance={"prune_partial_at": now.isoformat()})
    assert overview.health_problems(now) == []
    offsite.update_verify(check={"status": "failed", "failures": 2, "error": "boom"}, spot_restore={"status": "failed", "failures": 1, "error": "x"})
    assert [problem["key"] for problem in overview.health_problems(now)] == ["offsite-check"]  # one failed restore is not yet a problem


def test_the_dump_check_is_partial_when_it_runs_out_of_time_and_failed_without_its_trailer() -> None:
    jobs = {"postgres": {"snapshot_id": "pg"}}
    assert verify.spot_restore(Repo(_result(124)), jobs)["status"] == "partial"  # type: ignore[arg-type]
    broken = verify.spot_restore(Repo(_result(0, "COPY ...")), jobs, {"failures": 1})  # type: ignore[arg-type]
    assert broken["status"] == "failed" and broken["failures"] == 2
    whole = verify.spot_restore(Repo(_result(0, "-- PostgreSQL database cluster dump complete")), jobs, {"failures": 1})  # type: ignore[arg-type]
    assert whole["status"] == "ok" and whole["failures"] == 0


def test_prune_is_small_bounded_and_resumes_next_week(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify.shutil, "disk_usage", lambda _path: SimpleNamespace(free=10**12))
    repo = Repo(_result(124), _result(0), _result(1, stderr="lock"))
    assert verify.prune(repo, "t") == {"prune_partial_at": "t", "prune_error": None}  # type: ignore[arg-type]
    assert verify.prune(repo, "t") == {"pruned_at": "t", "prune_error": None}  # type: ignore[arg-type]
    assert verify.prune(repo, "t")["prune_error"] == "lock"  # type: ignore[arg-type]
    args, kwargs = repo.calls[0]
    assert "--max-repack-size" in args and args[args.index("--max-repack-size") + 1] == verify.PRUNE_REPACK_LIMIT and kwargs["timeout"] == verify.PRUNE_BOUND_SECONDS


def test_the_verify_record_is_its_own_file_so_neither_job_overwrites_the_other(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(offsite, "state_dir", lambda: tmp_path)
    offsite.write_state({"last_status": "ok", "maintenance": {"ran_at": "r", "pruned_at": "stale"}, "check": {"status": "stale"}})
    offsite.update_verify(check={"status": "ok"}, maintenance={"pruned_at": "p"}, legacy={"local_repository_bytes": 5})
    offsite.write_state({**offsite.read_state(), "last_status": "running", "legacy": {"drive_snapshots": 9}})  # what the backup writes back
    state = offsite.read_state()
    assert state["last_status"] == "running" and state["check"] == {"status": "ok"}
    assert state["maintenance"] == {"ran_at": "r", "pruned_at": "p"} and state["legacy"] == {"drive_snapshots": 9, "local_repository_bytes": 5}
    assert "check" not in json.loads((tmp_path / "state.json").read_text())


def test_the_backup_unit_no_longer_reads_anything_back() -> None:
    source = (Path(offsite.__file__)).read_text()
    for name in ("run_check", "spot_restore", "prune", "check\""):
        assert name not in source.split("def run_offsite")[1].split("def recover_state")[0]


def test_the_weekly_unit_is_low_priority_bounded_and_waits_for_the_backup() -> None:
    unit = (UNITS / "summitflow-host-verify.service").read_text()
    assert "Nice=19" in unit and "CPUWeight=10" in unit and "TimeoutStartSec=2h" in unit and "MemoryMax=" in unit
    assert "is-active --quiet summitflow-host-backup.service" in unit and "backup_verify" in unit
    assert "OnCalendar=Sun" in (UNITS / "summitflow-host-verify.timer").read_text()


def test_prune_waits_a_week_instead_of_filling_a_tight_scratch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify.shutil, "disk_usage", lambda _path: SimpleNamespace(free=verify.PRUNE_MIN_FREE_BYTES - 1))
    repo = Repo()
    assert verify.prune(repo, "t") == {"prune_partial_at": "t", "prune_error": None} and repo.calls == []  # type: ignore[arg-type]
