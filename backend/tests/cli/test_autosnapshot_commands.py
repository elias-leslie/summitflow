from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.commands import autosnapshot
from cli.lib.quick_snapshots import SnapshotError


@pytest.mark.parametrize(("command", "target"), [("prune", "prune_all"), ("sweep", "sweep_periodic")])
def test_concurrent_snapshot_job_is_a_skip_but_other_errors_fail(
    monkeypatch: pytest.MonkeyPatch, command: str, target: str
) -> None:
    def busy(**_: object) -> None:
        raise SnapshotError("Deferred: shared physical snapshot operation in progress")

    recorded: list[str] = []
    monkeypatch.setattr(autosnapshot, "write_sweep_state", lambda result: recorded.append(result))
    monkeypatch.setattr(autosnapshot, target, busy)
    result = CliRunner().invoke(autosnapshot.app, [command])
    assert result.exit_code == 0
    assert f"autosnap: {command} skipped: Deferred" in result.output

    def broken(**_: object) -> None:
        raise SnapshotError("manifest unreadable")

    monkeypatch.setattr(autosnapshot, target, broken)
    assert CliRunner().invoke(autosnapshot.app, [command]).exit_code != 0
    # A busy sweep leaves the last state alone; a failed one is recorded for the page and alert.
    assert recorded == (["manifest unreadable"] if command == "sweep" else [])


def test_sweep_records_result_and_newest_point(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from cli.lib import autosnapshot as lib

    monkeypatch.setattr(lib, "STATE_PATH", tmp_path / "autosnap-state.json")
    monkeypatch.setattr(lib, "newest_points", lambda: {"a": "2026-10-24T10:00:00+00:00", "b": "2026-10-24T11:00:00+00:00"})
    report = [{"project_id": "a", "status": "skip", "reason": "saved source unchanged"},
              {"project_id": "b", "status": "captured", "reason": "p1"}]
    monkeypatch.setattr(autosnapshot, "sweep_periodic", lambda: [])
    monkeypatch.setattr(autosnapshot, "LAST_SWEEP_REPORT", report)
    result = CliRunner().invoke(autosnapshot.app, ["sweep"])
    assert result.exit_code == 0
    assert "result:ok|newest:2026-10-24T11:00:00+00:00" in result.output
    state = lib.read_sweep_state()
    assert state["last_sweep_result"] == "ok"
    assert state["newest_point_at"] == "2026-10-24T11:00:00+00:00"
    assert state["projects"]["a"] == "2026-10-24T10:00:00+00:00"
    assert state["stale_after_hours"] == lib.DEFAULT_POLICY.stale_after_hours


def test_sweep_result_names_real_failures_only() -> None:
    from cli.lib.autosnapshot import sweep_result

    benign = [{"project_id": "a", "status": "skip", "reason": "interval not elapsed"},
              {"project_id": "b", "status": "skip", "reason": "Deferred: shared physical snapshot operation in progress"}]
    assert sweep_result(benign) == "ok"
    failed = [*benign, {"project_id": "c", "status": "skip", "reason": "Cannot inventory Btrfs boundaries: denied"}]
    assert sweep_result(failed) == "1 of 3 projects failed: c: Cannot inventory Btrfs boundaries: denied"
