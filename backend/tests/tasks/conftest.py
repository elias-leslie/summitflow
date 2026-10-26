"""Synthetic mounted scratch for backup routes that create disposable jobs."""

import pytest

from tests.backup_scratch_fixture import backup_job_scratch  # noqa: F401

_SCRATCH_TEST_MODULES = {"test_backup_publish.py"}


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


@pytest.fixture(autouse=True)
def isolated_backup_housekeeping(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scheduler tests never reap the live scratch mount or write live alerts."""
    if request.path.name == "test_backup_self_healing.py":
        return
    from app.tasks import backup_scheduler

    monkeypatch.setattr(backup_scheduler, "_reap_backup_scratch", lambda: {"removed": 0, "bytes": 0})
    monkeypatch.setattr(backup_scheduler, "_evaluate_alerts", lambda summary: None)
