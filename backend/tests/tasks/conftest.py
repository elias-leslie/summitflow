"""Synthetic mounted scratch for backup routes that create disposable jobs."""

import shutil
from pathlib import Path

import pytest

_SCRATCH_TEST_MODULES = {
    "test_backup.py", "test_backup_native_archive.py", "test_backup_native_archive_safety.py",
    "test_backup_native_infra_state.py", "test_backup_native_recovery.py", "test_backup_capture_payload.py",
    "test_backup_lean_git_recovery.py", "test_backup_offsite_parts.py", "test_backup_offsite_rclone.py",
    "test_backup_publish.py", "test_backup_smb_commands.py", "test_backup_independent_review.py",
    "test_backup_disposable_scratch.py",
    "test_backup_activity.py", "test_backup_native_restore_safety.py", "test_backup_capture_activity.py",
    "test_backup_restic_fixtures.py",
}


@pytest.fixture(autouse=True)
def backup_job_scratch(request, tmp_path, monkeypatch):
    if request.path.name not in _SCRATCH_TEST_MODULES:
        return None
    from app.utils import transient_scratch as scratch

    root = tmp_path / "mounted-scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(scratch, "SCRATCH_ROOT", root)
    original_is_mount = Path.is_mount
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root or original_is_mount(path))
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))
    return root
