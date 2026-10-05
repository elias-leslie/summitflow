"""Small isolated repositories only; never use configured production accounts."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.tasks.backup_restic import ResticAdapter, ResticConfig


@pytest.mark.skipif(shutil.which("restic") is None, reason="Pinned Restic fixture binary is not installed")
@pytest.mark.timeout(120)
def test_native_independent_copy_incremental_backup_and_verified_partial_restore(tmp_path: Path):
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    local_password = keys / "local-password"
    remote_password = keys / "remote-password"
    for path in (local_password, remote_password):
        path.write_text("synthetic-test-repository-password-only\n")
        path.chmod(0o600)
    root = tmp_path / "stable-payload"
    root.mkdir(mode=0o700)
    recovery = root / ".summitflow-recovery"
    recovery.mkdir()
    bundle = recovery / "fixture.bundle"
    original = bytes(range(256)) * 128
    bundle.write_bytes(original)
    config = ResticConfig(
        local_repository=tmp_path / "local-repository",
        remote_repository=str(tmp_path / "independent-repository"),
        local_password_file=local_password, remote_password_file=remote_password,
        key_directory=keys, hostname="synthetic-fixture",
    )
    adapter = ResticAdapter(config)
    readiness = adapter.readiness(local_only=True)
    assert readiness["ready"], readiness
    initialized = adapter.initialize()
    assert initialized["local_repository_id"] != initialized["remote_repository_id"]
    payload = {"snapshot_dir": root, "verification": {"verified": True}, "total_bytes": len(original)}
    first = adapter.save_payload("synthetic-fixture", payload)
    checkpoints = []
    copied = adapter.sync(first["snapshot_id"], persist=checkpoints.append)
    assert copied["status"] == "verified", copied
    assert copied["remote_snapshot_id"] != first["snapshot_id"]
    assert copied["state"]["verified_objects"]
    unchanged = adapter.save_payload("synthetic-fixture", payload)
    assert unchanged["parent_snapshot_id"] == first["snapshot_id"]
    # Tree metadata can change after the first read even when all file content
    # is reused, including metadata for the fixture's variable-length path.
    # Added raw bytes must remain below a fresh copy of the payload itself.
    assert unchanged["data_added_bytes"] < len(original)
    assert unchanged["snapshot_metrics"]["files_new"] == 0
    assert unchanged["snapshot_metrics"]["files_changed"] == 0
    assert unchanged["snapshot_metrics"]["files_unmodified"] == 1
    bundle.write_bytes(original + b"changed recovery payload")
    changed = adapter.save_payload("synthetic-fixture", payload)
    assert changed["parent_snapshot_id"] == unchanged["snapshot_id"]
    assert changed["data_added_bytes"] > 0
    copied_changed = adapter.sync(changed["snapshot_id"], state=checkpoints[-1], persist=checkpoints.append)
    assert copied_changed["status"] == "verified", copied_changed
    retry = adapter.sync(changed["snapshot_id"], state=checkpoints[-1], persist=checkpoints.append)
    assert retry["status"] == "verified", retry
    assert retry["verification"]["offsite"]["new_object_bytes"] == 0
    destination = tmp_path / "restore"
    destination.mkdir(mode=0o700)
    restored = adapter.restore(copied_changed["remote_snapshot_id"], destination, remote=True, include=[".summitflow-recovery/fixture.bundle"])
    restored_bundle = Path(restored["payload_root"]) / ".summitflow-recovery/fixture.bundle"
    assert restored_bundle.read_bytes() == bundle.read_bytes()
    check = adapter.check(remote=True, monthly_state={})
    assert check["verified"] and check["state"]["next_bucket"] == 2
