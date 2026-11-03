"""The ominull payload is refreshed through its owner before the Drive job reads it, and a failed refresh is never uploaded."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.tasks import backup_offsite as offsite
from app.tasks import backup_overview as overview
from app.tasks import backup_prepare as prepare
from app.tasks import backup_proxmox as px

SOURCE = "ominull-production-state"
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)
DIGEST = "a" * 64


class Repo:
    """Records what restic was asked to back up."""

    def __init__(self) -> None:
        self.target = SimpleNamespace(hostname="h")
        self.runtime = SimpleNamespace(excludes="e")
        self.calls: list[tuple[Any, ...]] = []

    def restic(self, *args: str, **_: Any) -> offsite.Result:
        self.calls.append(args)
        return offsite.Result(0, {"snapshot_id": "s" * 64, "total_bytes_processed": 1})


def _job(folder: Path) -> offsite.Job:
    return offsite.Job(name=SOURCE, kind="path", tags=("offsite",), required=False, paths=(str(folder),), prepare=True, guest="CT 150 ominull")


def test_the_drive_job_refreshes_the_folder_before_reading_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    order: list[str] = []
    monkeypatch.setattr(prepare, "prepare_source", lambda source, path: order.append("prepare") or {"status": "completed"})
    repo = Repo()
    monkeypatch.setattr(repo, "restic", lambda *a, **k: order.append("restic") or offsite.Result(0, {"snapshot_id": "s" * 64}))
    assert offsite.run_job(repo, _job(tmp_path))["status"] == "ok"  # type: ignore[arg-type]
    assert order == ["prepare", "restic"]


def test_a_failed_refresh_fails_the_job_with_its_reason_and_uploads_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def refuse(source: str, path: str) -> None:
        raise prepare.PrepareError("ominull could not refresh ominull-production-state (backup_secrets_not_sealed)")

    monkeypatch.setattr(prepare, "prepare_source", refuse)
    repo = Repo()
    record = offsite.run_job(repo, _job(tmp_path))  # type: ignore[arg-type]
    assert record["status"] == "failed" and "backup_secrets_not_sealed" in record["error"] and "not uploaded" in record["error"]
    assert repo.calls == []


def test_a_stopped_guest_is_offline_not_a_failure_and_not_uploaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prepare, "prepare_source", lambda source, path: None)
    repo = Repo()
    record = offsite.run_job(repo, _job(tmp_path))  # type: ignore[arg-type]
    assert record["status"] == "offline" and record["guest"] == "CT 150 ominull" and repo.calls == []


def test_only_the_registered_source_is_prepared(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sources = [{"id": SOURCE, "path": str(tmp_path), "enabled": True}, {"id": "blackbox-vault-archive", "path": str(tmp_path), "enabled": True}]
    monkeypatch.setattr(offsite.backup_store, "list_sources", lambda: sources)
    monkeypatch.setattr(offsite, "_off_host_disk", lambda path: True)
    jobs = {job.name: job for job in offsite.source_jobs()}
    assert jobs[SOURCE].prepare is True and jobs["blackbox-vault-archive"].prepare is False


def _state(monkeypatch: pytest.MonkeyPatch, **state: Any) -> None:
    monkeypatch.setattr(offsite, "read_state", lambda: state)


def test_the_owner_may_retire_its_old_generation_only_after_drive_holds_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    made = NOW - timedelta(days=1)
    (tmp_path / "manifest.json").write_text(json.dumps({"source_id": SOURCE, "backup_id": "bkp-1", "sha256": DIGEST, "completed_at": made.isoformat()}))
    _state(monkeypatch, repository="rclone:drive:x", jobs={SOURCE: {"time": NOW.isoformat(), "snapshot_id": "b" * 64}})
    proof = prepare._qualified_previous(SOURCE, tmp_path)
    assert proof and proof["backup_id"] == "bkp-1" and proof["snapshot_id"] == "b" * 64 and "rclone" not in json.dumps(proof)
    # The newest Drive copy predates this payload, so Drive does not hold it yet.
    _state(monkeypatch, repository="r", jobs={SOURCE: {"time": (made - timedelta(hours=1)).isoformat(), "snapshot_id": "b" * 64}})
    assert prepare._qualified_previous(SOURCE, tmp_path) is None
    _state(monkeypatch, repository="r", jobs={})
    assert prepare._qualified_previous(SOURCE, tmp_path) is None


def test_the_owner_failure_shows_only_its_fixed_code() -> None:
    assert prepare._owner_code(json.dumps({"status": "failed", "error": "backup_secrets_not_sealed"})) == "backup_secrets_not_sealed"
    assert prepare._owner_code(json.dumps({"status": "failed", "error": "see /home/x/secret.key"})) is None
    assert prepare._owner_code("not json") is None


def test_status_lists_a_stale_copy_as_a_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    target = {"target": "proxmox-gem/lxc/150 ominull", "status": "stale", "fresh": False, "age_hours": 192.0, "reason": "the files in the backup folder are old"}
    monkeypatch.setattr(px, "freshness_receipt", lambda now=None: {"targets": [target]})
    monkeypatch.setattr(overview, "local_summary", lambda **_: {"enabled": False})
    monkeypatch.setattr(overview.offsite, "read_state", lambda: {"last_success_at": NOW.isoformat()})
    problems = overview.health_problems(NOW)
    assert [p["key"] for p in problems] == ["stale-copy"] and "192h old" in problems[0]["message"]
