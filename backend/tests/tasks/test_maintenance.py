"""Tests for daily maintenance orchestration."""

from __future__ import annotations


def test_run_daily_maintenance_records_observable_summary(mocker) -> None:
    """Daily maintenance records summary metrics for operators."""
    from app.tasks.maintenance import run_daily_maintenance

    mocker.patch(
        "app.tasks.maintenance.cleanup_stale_tasks",
        return_value={"cancelled_count": 2},
    )
    mocker.patch(
        "app.tasks.maintenance.scan_history.fail_stale_running_scans",
        return_value=1,
    )
    mocker.patch(
        "app.tasks.maintenance.scan_history.cleanup_old_scan_history",
        return_value=3,
    )
    mocker.patch(
        "app.tasks.maintenance.notification_store.cleanup_old_notifications",
        return_value={"read_deleted": 4, "dismissed_deleted": 1},
    )
    mocker.patch(
        "app.tasks.maintenance.qcr_store.cleanup_old_results",
        return_value={"pass_deleted": 5, "skipped_deleted": 1, "fixed_deleted": 2},
    )
    mocker.patch(
        "app.tasks.maintenance.event_store.cleanup_old_events",
        return_value={"user_deleted": 6, "internal_deleted": 2, "total_deleted": 8},
    )
    mocker.patch(
        "app.tasks.maintenance.maintenance_store.cleanup_old_maintenance_runs",
        return_value=9,
    )
    mocker.patch(
        "app.tasks.maintenance.backup_store.cleanup_stale_backup_records",
        return_value=1,
    )
    mocker.patch(
        "app.tasks.maintenance.backup_store.cleanup_expired_backup_records",
        return_value=2,
    )
    record_run = mocker.patch("app.tasks.maintenance.maintenance_store.record_maintenance_run")

    result = run_daily_maintenance()

    assert result["status"] == "success"
    assert result["rows_cleaned"] == 39
    assert result["events_deleted"]["total_deleted"] == 8
    assert result["maintenance_runs_deleted"] == 9
    record_run.assert_called_once()
    assert record_run.call_args.args[:2] == ("daily_maintenance", "success")
    assert record_run.call_args.kwargs["rows_cleaned"] == 39
    assert record_run.call_args.kwargs["summary"]["events_deleted"]["user_deleted"] == 6
