"""Remote preparation identity and stale-state refusal."""

import json
from pathlib import Path

import pytest

from app.tasks import backup_ominull as backup


@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(backup, "SOURCE_PATH", tmp_path)
    archive = tmp_path / "lxc-150.tar"
    archive.write_bytes(b"qualified container fixture")
    response = {"schema_version": 1, "status": "completed", "project": "ominull",
                "source_id": backup.SOURCE_ID, "backup_id": "bkp-fixture", "target_id": 150,
                "archive_path": str(archive), "manifest_path": str(tmp_path / "manifest.json"),
                "size_bytes": archive.stat().st_size, "sha256": "a" * 64,
                "completed_at": "2026-10-06T16:00:00Z", "proxmox_task_id": "UPID:fixture"}
    (tmp_path / "manifest.json").write_text(json.dumps(response))
    return response


def test_qualified_owner_preparation(published: dict) -> None:
    assert backup.validate_preparation(published, backup_id="bkp-fixture") == published


@pytest.mark.parametrize("change", ["other-backup", "changed-manifest", "symlink"])
def test_preparation_refuses_stale_or_substituted_artifacts(published: dict, change: str) -> None:
    if change == "other-backup":
        published["backup_id"] = "bkp-older"
    elif change == "changed-manifest":
        Path(published["manifest_path"]).write_text("{}")
    else:
        archive = Path(published["archive_path"])
        content = archive.with_name("outside.tar")
        archive.rename(content)
        archive.symlink_to(content)
    with pytest.raises(ValueError):
        backup.validate_preparation(published, backup_id="bkp-fixture")


def test_source_misconfiguration_refuses_before_remote_work() -> None:
    with pytest.raises(RuntimeError, match="binding"):
        backup.prepare_ominull_backup(project_id="ominull", source_id=backup.SOURCE_ID,
                                      project_dir="/tmp/arbitrary", backup_id="bkp-fixture")


@pytest.mark.parametrize("fault", [None, "pending-capture", "unverified", "wrong-source", "wrong-generation"])
def test_staging_retirement_requires_qualified_matching_capture(
    published: dict, monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    record = {"id": "bkp-fixture", "project_id": "ominull", "source_id": backup.SOURCE_ID,
              "status": "completed_pending_upload", "verified": True,
              "verification_json": {"snapshot_id": "b" * 64, "repository_id": "c" * 64,
                                    "remote_preparation": published.copy()}}
    if fault == "pending-capture":
        record["status"] = "running"
    elif fault == "unverified":
        record["verified"] = False
    elif fault == "wrong-source":
        record["source_id"] = "other"
    elif fault == "wrong-generation":
        record["verification_json"]["remote_preparation"]["sha256"] = "d" * 64
    monkeypatch.setattr(backup.backup_store, "get_backup", lambda _: record)
    result = backup.qualified_previous()
    assert (result is not None) == (fault is None)
    if result:
        assert result["backup_id"] == published["backup_id"]
        assert result["sha256"] == published["sha256"]
