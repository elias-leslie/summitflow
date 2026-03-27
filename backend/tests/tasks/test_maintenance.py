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
    mocker.patch(
        "app.tasks.maintenance.cleanup_host_artifacts",
        return_value={
            "status": "success",
            "items_deleted": 3,
            "bytes_reclaimed": 4096,
            "review_candidates": [{"path": "/tmp/legacy", "reason": "legacy_project_root"}],
        },
    )
    record_run = mocker.patch("app.tasks.maintenance.maintenance_store.record_maintenance_run")

    result = run_daily_maintenance()

    assert result["status"] == "success"
    assert result["rows_cleaned"] == 42
    assert result["bytes_reclaimed"] == 4096
    assert result["events_deleted"]["total_deleted"] == 8
    assert result["maintenance_runs_deleted"] == 9
    assert result["host_retention"]["items_deleted"] == 3
    record_run.assert_called_once()
    assert record_run.call_args.args[:2] == ("daily_maintenance", "success")
    assert record_run.call_args.kwargs["rows_cleaned"] == 42
    assert record_run.call_args.kwargs["summary"]["events_deleted"]["user_deleted"] == 6


def test_run_daily_maintenance_becomes_partial_when_host_retention_reports_partial(
    mocker,
) -> None:
    from app.tasks.maintenance import run_daily_maintenance

    mocker.patch(
        "app.tasks.maintenance.cleanup_stale_tasks",
        return_value={"cancelled_count": 0},
    )
    mocker.patch("app.tasks.maintenance.purge_terminal_tasks", return_value=0)
    mocker.patch(
        "app.tasks.maintenance.scan_history.fail_stale_running_scans",
        return_value=0,
    )
    mocker.patch(
        "app.tasks.maintenance.scan_history.cleanup_old_scan_history",
        return_value=0,
    )
    mocker.patch(
        "app.tasks.maintenance.notification_store.cleanup_old_notifications",
        return_value={},
    )
    mocker.patch(
        "app.tasks.maintenance.qcr_store.cleanup_old_results",
        return_value={},
    )
    mocker.patch(
        "app.tasks.maintenance.event_store.cleanup_old_events",
        return_value={"total_deleted": 0},
    )
    mocker.patch(
        "app.tasks.maintenance.maintenance_store.cleanup_old_maintenance_runs",
        return_value=0,
    )
    mocker.patch(
        "app.tasks.maintenance.backup_store.cleanup_stale_backup_records",
        return_value=0,
    )
    mocker.patch(
        "app.tasks.maintenance.backup_store.cleanup_expired_backup_records",
        return_value=0,
    )
    mocker.patch(
        "app.tasks.maintenance.cleanup_host_artifacts",
        return_value={
            "status": "partial",
            "items_deleted": 0,
            "bytes_reclaimed": 0,
            "errors": ["docker image prune failed"],
        },
    )

    result = run_daily_maintenance()

    assert result["status"] == "partial"
