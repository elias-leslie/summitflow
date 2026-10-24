"""The host restore test sets restore_verified only on a recent pass and always cleans up."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.tasks import backup_btrbk as host
from app.tasks import backup_btrbk_restore_test as restore

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(host, "_state_root", lambda: tmp_path)
    return tmp_path


def write_receipt(state: Path, status: str, completed: datetime) -> None:
    (state / "restore-test.json").write_text(json.dumps({"status": status, "completed_at": completed.isoformat()}))


def test_restore_verified_needs_a_recent_pass(state: Path) -> None:
    assert restore.host_restore_status(now=NOW)["restore_verified"] is False
    write_receipt(state, "failed", NOW - timedelta(days=1))
    assert restore.host_restore_status(now=NOW)["restore_verified"] is False
    write_receipt(state, "verified", NOW - timedelta(days=1))
    status = restore.host_restore_status(now=NOW)
    assert status["restore_verified"] is True
    assert status["restore_tested_at"] == (NOW - timedelta(days=1)).isoformat()
    write_receipt(state, "verified", NOW - timedelta(days=restore.RESTORE_VERIFIED_DAYS + 1))
    assert restore.host_restore_status(now=NOW)["restore_verified"] is False


def test_pass_inside_cadence_skips(state: Path) -> None:
    write_receipt(state, "verified", NOW - timedelta(days=3))
    assert restore.run_host_restore_test(now=NOW)["reason"] == "monthly-cadence"


@pytest.mark.parametrize("fails", [None, "home", "boot", "raise"])
def test_run_records_result_and_deletes_received_trees(monkeypatch: pytest.MonkeyPatch, state: Path, fails: str | None) -> None:
    write_receipt(state, "failed", NOW - timedelta(days=3))
    commands: list[list[str]] = []
    monkeypatch.setattr(host, "_configuration", lambda: [{"snapshot_name": name, "snapshot_path": f"/src/{name}/.btrbk", "source_url": f"/src/{name}"}
                                                         for name in ("root", "home", "workspaces")])
    monkeypatch.setattr(host, "_checked", lambda args, **_: commands.append(args) or "")
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr(host, "_run", run)
    def compare(name: str, *_: Any) -> dict[str, Any]:
        if fails == "raise":
            raise RuntimeError("send failed")
        return {"ok": name != fails, **({"error": "1 of 48 sampled files differ"} if name == fails else {})}
    monkeypatch.setattr(restore, "_compare", compare)
    monkeypatch.setattr(restore, "_boot_path", lambda: {"ok": fails != "boot", "missing": [] if fails != "boot" else ["boot:grub/grub.cfg"]})
    result = restore.run_host_restore_test(now=NOW)
    saved = json.loads((state / "restore-test.json").read_text())
    assert saved["status"] == result["status"] == ("verified" if fails is None else "failed")
    if fails == "home":
        assert saved["error"] == "home: 1 of 48 sampled files differ"
    if fails == "raise":
        assert saved["error"] == "send failed"
    # The run directory is removed even when a step raised.
    assert any(command[:3] == ["sudo", "-n", "rmdir"] for command in commands)
    assert restore.host_restore_status(now=NOW)["restore_verified"] is (fails is None)


def test_counts_or_sample_mismatch_fails_the_subvolume(monkeypatch: pytest.MonkeyPatch, state: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(restore, "NATIVE_TARGET", tmp_path)
    monkeypatch.setattr(restore, "_latest_point", lambda name: Path(f"/t7/{name}.20261024T023015-0400"))
    monkeypatch.setattr(restore, "run_bulk_process", lambda *a, **k: None)
    monkeypatch.setattr(host, "_run", lambda args: subprocess.CompletedProcess(args, 0, stdout="", stderr=""))
    monkeypatch.setattr(restore.shutil, "disk_usage", lambda _: type("U", (), {"used": 1, "free": 10**15})())
    counts = {"restored": {"files": 3, "links": 0, "dirs": 1, "sample": ["a", "b"]}, "source": {"files": 3, "links": 0, "dirs": 1, "sample": []}}
    digests = {"restored": {"a": [1, 5, "x"], "b": [2, 5, "y"]}, "source": {"a": [1, 5, "x"], "b": [2, 5, "y"]}, "live": {"a": [1, 5, "x"], "b": [9, 6, "z"]}}
    def probe(mode: str, root: str, *_: str, **__: Any) -> dict[str, Any]:
        label = "restored" if "/restore/" in root else "source" if ".btrbk" in root else "live"
        if mode == "count":
            return dict(counts.get(label, counts["source"]))
        return digests[label]
    monkeypatch.setattr(restore, "_probe", probe)
    row = {"snapshot_path": "/src/.btrbk", "source_url": "/src"}
    ok = restore._compare("home", row, Path("/t7/restore/run"), "seed")
    assert ok["ok"] is True and ok["sample_matched"] == 2 and ok["live_compared"] == 1 and ok["live_matched"] == 1
    digests["restored"]["b"] = [2, 5, "corrupt"]
    bad = restore._compare("home", row, Path("/t7/restore/run"), "seed")
    assert bad["ok"] is False and "1 of 2 sampled files differ" in bad["error"]
    digests["restored"]["b"] = [2, 5, "y"]
    counts["restored"] = {"files": 2, "links": 0, "dirs": 1, "sample": ["a", "b"]}
    assert "counts differ" in restore._compare("home", row, Path("/t7/restore/run"), "seed")["error"]
