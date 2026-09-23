"""A single controller renewal path preserves elapsed time without claiming progress."""

from collections.abc import Awaitable
from datetime import timedelta
from unittest.mock import Mock

import pytest


def test_progress_renews_only_elapsed_seconds_and_retains_fraction(monkeypatch) -> None:
    from app.workflows import backup_progress

    # Total verified work exceeds the original 900s workflow deadline.
    clock = iter([100.0, 100.0, 875.6, 1650.8, 1651.1])
    monkeypatch.setattr(backup_progress.time, "monotonic", lambda: next(clock))
    ctx = Mock()
    ctx.done.return_value = False
    progress = backup_progress.make_backup_progress_callback(ctx)
    ctx.refresh_timeout.assert_not_called()
    progress()
    ctx.refresh_timeout.assert_not_called()
    progress._renew()
    progress._renew()
    progress._renew()
    assert [call.args[0] for call in ctx.refresh_timeout.call_args_list] == [
        timedelta(seconds=775), timedelta(seconds=775), timedelta(seconds=1),
    ]


def test_scheduled_source_forwards_progress(monkeypatch) -> None:
    from app.tasks import backup_scheduler

    progress = Mock()
    create = Mock(return_value={"status": "completed"})
    monkeypatch.setattr(backup_scheduler, "create_backup", create)
    monkeypatch.setattr(backup_scheduler.backup_store, "update_source_last_run", Mock())
    backup_scheduler._process_due_source(
        {"id": "source", "frequency": "daily"}, on_progress=progress,
    )
    assert create.call_args.kwargs["on_progress"] is progress


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["create", "sync", "scheduled"])
async def test_backup_workflows_pass_progress_callback(monkeypatch, kind) -> None:
    from app.workflows import scheduled, utility
    from app.workflows.models import BackupInput, EmptyInput, OffsiteSyncInput

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(utility.asyncio, "to_thread", inline)
    monkeypatch.setattr(scheduled, "_system_schedule_enabled", lambda _: True)
    execute = Mock(return_value={"status": "completed"})
    ctx = Mock()
    if kind == "create":
        monkeypatch.setattr("app.tasks.backup.create_backup", execute)
        call = utility.backup_create_wf._task.fn(BackupInput(project_id="source", source_id="source"), ctx)
    elif kind == "sync":
        monkeypatch.setattr("app.tasks.backup_executor.sync_backup_offsite", execute)
        call = utility.backup_offsite_sync_wf._task.fn(OffsiteSyncInput(backup_id="backup", source_id="source"), ctx)
    else:
        monkeypatch.setattr("app.tasks.backup.run_scheduled_backups", execute)
        call = scheduled.scheduled_backups_wf._task.fn(EmptyInput(), ctx)
    assert isinstance(call, Awaitable)
    await call
    assert callable(execute.call_args.kwargs["on_progress"])
    ctx.refresh_timeout.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt_id", [None, "queued-attempt"])
async def test_sync_preflight_failure_closes_only_current_attempt_and_releases_lease(monkeypatch, attempt_id) -> None:
    from app.workflows import utility
    from app.workflows.models import OffsiteSyncInput

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(utility.asyncio, "to_thread", inline)
    monkeypatch.setattr("app.tasks.backup_executor.sync_backup_offsite", Mock(side_effect=FileNotFoundError("missing archive")))
    merged, released = Mock(return_value={"id": "backup"}), Mock()
    monkeypatch.setattr("app.storage.backups.merge_backup_verification_json", merged)
    monkeypatch.setattr("app.tasks.backup_lock.release_backup_lock", released)
    ctx = Mock(workflow_run_id="run")
    call = utility.backup_offsite_sync_wf._task.fn(
        OffsiteSyncInput(source_id="source", backup_id="backup", owner_token="owner", attempt_id=attempt_id), ctx,
    )
    assert isinstance(call, Awaitable)
    result = await call
    assert result == {"status": "failed", "backup_id": "backup", "error": "missing archive"}
    assert merged.call_args.kwargs["expected_activity_run_id"] == (attempt_id or "run")
    assert merged.call_args.args[1]["activity"]["active"] is False
    released.assert_called_once_with("source", "owner")
