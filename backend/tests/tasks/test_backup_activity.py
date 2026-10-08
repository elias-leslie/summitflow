"""Opaque bulk waits are visible and cancellable, not elapsed-time failures."""

import subprocess
import sys
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest


def test_bulk_wait_past_attention_threshold_does_not_kill_healthy_child(monkeypatch) -> None:
    from app.tasks import backup_activity

    activity = Mock()
    activity.cancelled.is_set.return_value = False
    monkeypatch.setattr(backup_activity, "current_activity", lambda: activity)
    result = backup_activity.run_bulk_process(
        [sys.executable, "-c", "import time; time.sleep(0.05); print('done')"],
        attention_after=0.01,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "done"
    activity.start_phase.assert_called_once()
    activity.check_cancelled.assert_called()


def test_explicit_bulk_cancel_kills_and_reaps_owned_child(monkeypatch) -> None:
    from app.tasks import backup_activity

    processes = []
    original = subprocess.Popen

    def popen(*args, **kwargs):
        proc = original(*args, **kwargs)
        processes.append(proc)
        return proc

    activity = Mock()
    activity.check_cancelled.side_effect = backup_activity.BackupCancelled("Cancelled by owner")
    monkeypatch.setattr(backup_activity, "current_activity", lambda: activity)
    monkeypatch.setattr(backup_activity.subprocess, "Popen", popen)
    with pytest.raises(backup_activity.BackupCancelled):
        backup_activity.run_bulk_process([sys.executable, "-c", "import time; time.sleep(60)"])
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_provider_failure_still_returns_nonzero() -> None:
    from app.tasks.backup_activity import run_bulk_process

    result = run_bulk_process([sys.executable, "-c", "import sys; sys.exit(7)"])
    assert result.returncode == 7


def test_explicit_bulk_timeout_kills_and_reaps_owned_process_group(tmp_path, monkeypatch):
    from app.tasks import backup_activity

    processes = []
    original = subprocess.Popen

    def popen(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(backup_activity.subprocess, "Popen", popen)
    marker = tmp_path / "child-pid"
    child_code = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
    code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)"
    with pytest.raises(subprocess.TimeoutExpired):
        backup_activity.run_bulk_process(
            [sys.executable, "-c", code], timeout=1,
        )
    assert len(processes) == 1
    assert processes[0].poll() is not None
    child = Path(f"/proc/{marker.read_text()}/stat")
    assert not child.exists() or child.read_text().rsplit(")", 1)[1].split()[0] == "Z"


def test_capacity_refusal_kills_and_reaps_owned_process_group(tmp_path, monkeypatch):
    from app.tasks import backup_activity
    from app.utils.transient_scratch import ScratchError

    processes = []
    original = subprocess.Popen

    def popen(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    marker = tmp_path / "child-pid"
    child_code = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
    code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)"
    checks = []

    def capacity():
        checks.append(True)
        if marker.exists():
            raise ScratchError("fixture reserve crossed")

    monkeypatch.setattr(backup_activity.subprocess, "Popen", popen)
    monkeypatch.setattr(backup_activity, "CONTROL_POLL_SECONDS", 0.01)
    with pytest.raises(ScratchError, match="fixture reserve crossed"):
        backup_activity.run_bulk_process([sys.executable, "-c", code], capacity_check=capacity)
    assert len(checks) >= 2
    assert len(processes) == 1 and processes[0].poll() is not None
    child = Path(f"/proc/{marker.read_text()}/stat")
    assert not child.exists() or child.read_text().rsplit(")", 1)[1].split()[0] == "Z"


def test_unknown_wait_is_visible_without_inventing_verified_progress(monkeypatch) -> None:
    from app.tasks import backup_activity

    attention_written, renewed = Event(), Event()
    saved = {"activity": {}}

    def merge(_backup_id, update, **_kwargs):
        saved["activity"].update(update["activity"])
        if update["activity"].get("attention"):
            attention_written.set()
        return {"verification_json": saved}

    monkeypatch.setattr(backup_activity, "CONTROL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(backup_activity, "CONTROL_DB_POLL_SECONDS", 0.01)
    monkeypatch.setattr(backup_activity, "BACKUP_LOCK_RENEW_INTERVAL", 0.01)
    monkeypatch.setattr(backup_activity.backup_store, "get_backup", lambda _: {"verification_json": saved})
    monkeypatch.setattr(backup_activity.backup_store, "merge_backup_verification_json", merge)
    activity = backup_activity.BackupActivity("run", lambda: False, renewed.set)
    with activity.bind("backup"):
        activity.start_phase("upload", "part", attention_after=0.01)
        assert attention_written.wait(1)
        assert renewed.wait(1)
        assert saved["activity"]["active"] is True
        assert saved["activity"]["verified_parts"] == 0
        assert saved["activity"]["last_verified_at"] is None
    assert saved["activity"]["active"] is False


def test_cancelled_remote_attempt_retains_local_checkpoint_and_unknown_outcome(monkeypatch, tmp_path) -> None:
    from app.tasks import backup_activity

    saved = {"activity": {}}
    def merge(_backup_id, update, **_kwargs):
        saved["activity"].update(update["activity"])
        return {"verification_json": saved}

    update_status = Mock()
    monkeypatch.setattr(backup_activity.backup_store, "get_backup", lambda _: {"verification_json": saved})
    monkeypatch.setattr(backup_activity.backup_store, "merge_backup_verification_json", merge)
    monkeypatch.setattr(backup_activity.backup_store, "update_backup_status", update_status)
    archive = tmp_path / "saved.age"
    archive.write_bytes(b"retained ciphertext")
    activity = backup_activity.BackupActivity("run", lambda: False, Mock())
    with activity.bind("backup"):
        activity.record_local_archive({
            "verification": {"verified": True}, "location": str(archive),
            "archive_name": archive.name, "total_bytes": archive.stat().st_size,
        })
        activity.start_phase("upload")
        activity.cancelled.set()
        activity.record_offsite_result({"status": "failed"})
    assert update_status.call_args.args == ("backup", "completed")
    assert archive.read_bytes() == b"retained ciphertext"
    assert saved["activity"]["phase"] == "cancelled"
    assert saved["activity"]["active"] is False
    assert saved["activity"]["remote_outcome_unknown"] is True


def test_state_outage_does_not_busy_poll_spam_or_suppress_renewal(monkeypatch) -> None:
    from app.tasks import backup_activity

    renewal = Mock()
    activity = backup_activity.BackupActivity("run", lambda: False, renewal)
    activity.backup_id = "backup"
    activity._stop = Mock()
    activity._stop.wait.side_effect = [False] * 10 + [True]
    clock = iter(range(11))
    monkeypatch.setattr(backup_activity.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(backup_activity, "BACKUP_LOCK_RENEW_INTERVAL", 3)
    read = Mock(side_effect=ConnectionError("DB unavailable"))
    logger = Mock()
    monkeypatch.setattr(backup_activity.backup_store, "get_backup", read)
    monkeypatch.setattr(backup_activity, "logger", logger)
    activity._monitor()
    assert read.call_count == 2
    assert logger.exception.call_count == 1
    assert renewal.call_count == 3


@pytest.mark.parametrize("infrastructure", [False, True])
def test_post_lease_closeout_does_not_overwrite_newer_retry_metadata(monkeypatch, infrastructure) -> None:
    from app.tasks import backup_executor, backup_infra

    store = backup_executor.backup_store
    monkeypatch.setattr(store, "get_backup", lambda _: {
        "verification_json": {"activity": {"run_id": "new-retry", "active": True}},
    })
    updated = Mock()
    monkeypatch.setattr(store, "update_backup_status", updated)
    parsed: dict[str, object] = {"verification": {"verified": True, "offsite": {"status": "verified"}}}
    if infrastructure:
        backup_infra._handle_success("backup", parsed)
    else:
        backup_executor._handle_backup_success("backup", "project", parsed)
    assert "verification_json" not in updated.call_args.kwargs


def test_terminal_persistence_failure_still_resets_activity_context(monkeypatch) -> None:
    from app.tasks import backup_activity

    def merge(_id, update, **_kwargs):
        if update["activity"].get("active") is False:
            raise ConnectionError("terminal DB write failed")
        return {}

    monkeypatch.setattr(backup_activity.backup_store, "get_backup", lambda _: {})
    monkeypatch.setattr(backup_activity.backup_store, "merge_backup_verification_json", merge)
    activity = backup_activity.BackupActivity("run", lambda: False, Mock())
    with pytest.raises(ConnectionError, match="terminal DB write failed"), activity.bind("backup"):
        assert backup_activity.current_activity() is activity
    assert backup_activity.current_activity() is None


def test_queued_attempt_bind_honors_cancel_accepted_during_state_write(monkeypatch) -> None:
    from app.tasks import backup_activity

    monkeypatch.setattr(backup_activity.backup_store, "get_backup", lambda _: {
        "verification_json": {"activity": {"run_id": "attempt", "cancel_requested": False}},
    })
    merged = Mock(return_value={"verification_json": {"activity": {"run_id": "attempt", "cancel_requested": True}}})
    monkeypatch.setattr(backup_activity.backup_store, "merge_backup_verification_json", merged)
    activity = backup_activity.BackupActivity("attempt", lambda: False, Mock(), queued_attempt=True)
    with activity.bind("backup"), pytest.raises(backup_activity.BackupCancelled):
        activity.check_cancelled()
    assert all(call.kwargs["expected_activity_run_id"] == "attempt" for call in merged.call_args_list)


def test_stale_queued_attempt_cannot_bind_over_new_attempt(monkeypatch) -> None:
    from app.tasks import backup_activity

    monkeypatch.setattr(backup_activity.backup_store, "get_backup", lambda _: {})
    merged = Mock(return_value=None)
    monkeypatch.setattr(backup_activity.backup_store, "merge_backup_verification_json", merged)
    activity = backup_activity.BackupActivity("old-attempt", lambda: False, Mock(), queued_attempt=True)
    with pytest.raises(backup_activity.BackupCancelled, match="no longer current"), activity.bind("backup"):
        pytest.fail("stale attempt must not enter backup execution")
    assert merged.call_args.kwargs["expected_activity_run_id"] == "old-attempt"
    assert backup_activity.current_activity() is None
