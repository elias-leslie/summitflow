"""Synthetic mounted scratch for backup routes that create disposable jobs."""

import pytest

from tests.backup_scratch_fixture import backup_job_scratch  # noqa: F401

_SCRATCH_TEST_MODULES = {
    "test_backup.py", "test_backup_native_archive.py", "test_backup_native_archive_safety.py",
    "test_backup_native_infra_state.py", "test_backup_native_recovery.py", "test_backup_capture_payload.py",
    "test_backup_lean_git_recovery.py", "test_backup_offsite_parts.py", "test_backup_offsite_rclone.py",
    "test_backup_publish.py", "test_backup_smb_commands.py", "test_backup_independent_review.py",
    "test_backup_disposable_scratch.py",
    "test_backup_activity.py", "test_backup_native_restore_safety.py", "test_backup_capture_activity.py",
    "test_backup_restic_fixtures.py",
    "test_backup_codex_essentials.py", "test_backup_git_index_states.py", "test_backup_portable_lifecycle.py",
    "test_backup_jsonl_capture.py",
}


@pytest.fixture(autouse=True)
def backup_task_scratch(request: pytest.FixtureRequest) -> None:
    if request.path.name in _SCRATCH_TEST_MODULES:
        request.getfixturevalue("backup_job_scratch")


@pytest.fixture(autouse=True)
def isolated_native_host_state(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep tests away from the live btrbk receipts and real host commands.

    The settings file can enable native host backup on this workstation, so a
    scheduler test that reaches the host path would otherwise resume the live
    receipt against the test catalogue. Tests opt back in explicitly.
    """
    from app.tasks import backup_btrbk

    root = tmp_path_factory.mktemp("native-host-state")
    root.chmod(0o700)
    monkeypatch.setenv("BACKUP_BTRBK_ENABLED", "false")
    monkeypatch.setattr(backup_btrbk, "_state_root", lambda: root)
