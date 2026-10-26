"""`st cleanup host`: the daily host retention on demand, skipped while a recent run exists."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from cli.commands import cleanup

runner = CliRunner()


def _patch(mocker, runs: list[dict], summary: dict):
    mocker.patch("app.storage.maintenance_runs.list_maintenance_runs", side_effect=lambda **kw: runs if kw["workflow_name"] == "daily_maintenance" else [])
    record = mocker.patch("app.storage.maintenance_runs.record_maintenance_run")
    run = mocker.patch("app.tasks.host_retention.cleanup_host_artifacts", return_value=summary)
    return run, record


def test_a_fresh_daily_run_is_not_repeated(mocker) -> None:
    run, record = _patch(mocker, [{"started_at": datetime.now(UTC) - timedelta(hours=5)}], {"status": "success"})
    result = runner.invoke(cleanup.app, ["host", "--if-stale", "30"])
    assert result.exit_code == 0 and '"reason": "fresh"' in result.output
    assert not run.called and not record.called


def test_a_stale_or_missing_run_is_replaced_and_recorded(mocker) -> None:
    run, record = _patch(mocker, [{"started_at": datetime.now(UTC) - timedelta(hours=40)}], {"status": "success", "items_deleted": 3, "errors": []})
    result = runner.invoke(cleanup.app, ["host", "--if-stale", "30"])
    assert result.exit_code == 0 and run.called
    assert record.call_args.args[:2] == ("host_retention", "success") and record.call_args.kwargs["rows_cleaned"] == 3


def test_a_failed_step_exits_nonzero(mocker) -> None:
    _patch(mocker, [], {"status": "partial", "errors": ["uv: boom"]})
    result = runner.invoke(cleanup.app, ["host"])
    assert result.exit_code == 1
