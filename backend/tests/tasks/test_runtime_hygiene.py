"""Tests for runtime hygiene maintenance audit."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _backup_row(*, source_id: str, hours_ago: float, status: str = "completed") -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "source_id": source_id,
        "source_name": source_id,
        "source_type": "project",
        "enabled": True,
        "next_run_at": None,
        "last_success_at": (now - timedelta(hours=hours_ago)).isoformat(),
        "failure_count_7d": 0,
        "last_backup_status": status,
        "pending_upload_count": 0,
        "last_restore_tested_at": (now - timedelta(days=1)).isoformat(),
        "last_restore_test_ok": True,
        "last_drill_at": None,
        "last_drill_ok": None,
        "last_drill_backup_id": None,
    }


def _candidate(table: str = "session_events", severity: str = "warning") -> dict[str, object]:
    return {
        "schema": "public",
        "table": table,
        "table_ref": f"public.{table}",
        "total_bytes": 256 * 1024 * 1024,
        "total_mb": 256.0,
        "n_live_tup": 10000,
        "n_dead_tup": 2500,
        "dead_pct": 20.0 if severity == "critical" else 12.5,
        "dead_bytes": 64 * 1024 * 1024,
        "dead_mb": 64.0,
        "severity": severity,
        "last_autovacuum": None,
        "last_vacuum": None,
    }


def test_query_bloat_candidates_returns_unavailable_when_db_url_missing(mocker) -> None:
    from app.tasks.runtime_hygiene import _query_bloat_candidates

    mocker.patch("app.tasks.runtime_hygiene.get_db_url_for_project", return_value=None)

    result = _query_bloat_candidates("agent-hub")

    assert result["status"] == "unavailable"
    assert result["reason"] == "db_url_missing"
    assert result["candidates"] == []



def test_project_target_vacuums_when_backup_is_fresh(mocker) -> None:
    from app.tasks.runtime_hygiene import _project_target

    backup_rows = {"summitflow": _backup_row(source_id="summitflow", hours_ago=2)}
    mocker.patch(
        "app.tasks.runtime_hygiene._journal_findings",
        return_value={"status": "ok", "pattern": "summitflow-*", "issue_count": 0, "created_task_ids": [], "errors": []},
    )
    mocker.patch(
        "app.tasks.runtime_hygiene._query_bloat_candidates",
        side_effect=[
            {"status": "warning", "project_id": "summitflow", "candidates": [_candidate()]},
            {"status": "ok", "project_id": "summitflow", "candidates": []},
        ],
    )
    mocker.patch("app.tasks.runtime_hygiene._recent_action_succeeded", return_value=False)
    vacuum = mocker.patch(
        "app.tasks.runtime_hygiene._vacuum_analyze_table",
        return_value={"status": "completed", "table": "session_events"},
    )
    create_or_refresh = mocker.patch("app.tasks.runtime_hygiene._create_or_refresh_issue_task")

    summary, issues, created_task_ids, reused_task_ids = _project_target(
        "summitflow",
        backup_rows=backup_rows,
        latest_runtime_hygiene=None,
        now=datetime.now(UTC),
    )

    assert vacuum.call_count == 1
    assert issues == []
    assert created_task_ids == []
    assert reused_task_ids == []
    assert create_or_refresh.call_count == 0
    assert summary["status"] == "ok"
    assert summary["actions_taken"][0]["type"] == "vacuum_analyze"



def test_project_target_creates_issues_when_backup_stays_stale(mocker) -> None:
    from app.tasks.runtime_hygiene import _project_target

    backup_rows = {"agent-hub": _backup_row(source_id="agent-hub", hours_ago=80, status="failed")}
    mocker.patch(
        "app.tasks.runtime_hygiene._journal_findings",
        return_value={"status": "ok", "pattern": "agent-hub-*", "issue_count": 0, "created_task_ids": [], "errors": []},
    )
    mocker.patch(
        "app.tasks.runtime_hygiene._ensure_backup_fresh",
        return_value={
            "status": "stale",
            "source_type": "project",
            "source_id": "agent-hub",
            "backup_age_hours": 80.0,
            "restore_age_hours": 24.0,
            "drill_age_hours": None,
            "is_fresh": False,
            "restore_validation_ok": False,
            "pending_upload_count": 0,
            "last_backup_status": "failed",
            "last_success_at": None,
            "last_restore_tested_at": None,
            "last_restore_test_ok": False,
            "last_drill_at": None,
            "last_drill_ok": None,
            "last_drill_backup_id": None,
        },
    )
    mocker.patch(
        "app.tasks.runtime_hygiene._query_bloat_candidates",
        return_value={"status": "warning", "project_id": "agent-hub", "candidates": [_candidate(table="usage_stats")], "candidate_count": 1},
    )
    mocker.patch(
        "app.tasks.runtime_hygiene._create_or_refresh_issue_task",
        side_effect=[("task-backup", True), ("task-restore", True), ("task-bloat", True)],
    )

    summary, issues, created_task_ids, reused_task_ids = _project_target(
        "agent-hub",
        backup_rows=backup_rows,
        latest_runtime_hygiene=None,
        now=datetime.now(UTC),
    )

    assert summary["status"] == "critical"
    assert summary["bloat"]["skipped_candidates"][0]["skip_reason"] == "backup_prerequisite_not_satisfied"
    assert {issue["issue_type"] for issue in issues} == {"backup", "restore_validation", "db_bloat"}
    assert created_task_ids == ["task-backup", "task-restore", "task-bloat"]
    assert reused_task_ids == []



def test_host_pressure_runs_cleanup_even_when_recent_runtime_hygiene_exists(mocker) -> None:
    from app.tasks.runtime_hygiene import _host_pressure

    before = {
        "disk": {"mount_path": "/", "percent_used": 89.0, "free_gb": 11.0, "status": "warning"},
        "disks": [],
        "memory": {"percent_used": 40.0, "status": "ok"},
        "cpu": {"percent_used": 5.0, "status": "ok"},
    }
    after = {
        "disk": {"mount_path": "/", "percent_used": 79.0, "free_gb": 17.0, "status": "ok"},
        "disks": [],
        "memory": {"percent_used": 40.0, "status": "ok"},
        "cpu": {"percent_used": 5.0, "status": "ok"},
    }
    cleanup_result = {"status": "success", "bytes_reclaimed": 5 * 1024 * 1024 * 1024}
    mocker.patch("app.tasks.runtime_hygiene._collect_host_snapshot", side_effect=[before, after])
    mocker.patch("app.tasks.runtime_hygiene._run_started_within", return_value=False)
    cleanup = mocker.patch("app.tasks.runtime_hygiene.cleanup_host_artifacts", return_value=cleanup_result)
    mocker.patch("app.tasks.runtime_hygiene._create_or_refresh_issue_task", return_value=("task-host", False))

    host, actions_taken, issues, created_task_ids, reused_task_ids = _host_pressure(
        latest_runtime_hygiene={"started_at": datetime.now(UTC).isoformat()},
        now=datetime.now(UTC),
    )

    cleanup.assert_called_once_with()
    assert host["cleanup"] == cleanup_result
    assert actions_taken[0]["type"] == "host_cleanup"
    assert actions_taken[0]["status"] == "completed"
    assert issues == []
    assert created_task_ids == []
    assert reused_task_ids == []



def test_run_runtime_hygiene_records_summary(mocker) -> None:
    from app.tasks.runtime_hygiene import run_runtime_hygiene

    host = {
        "disk": {"mount_path": "/", "percent_used": 70.0, "free_gb": 20.0, "status": "ok"},
        "disks": [],
        "memory": {"percent_used": 40.0, "status": "ok"},
        "cpu": {"percent_used": 5.0, "status": "ok"},
    }
    target_summary = {
        "project_id": "summitflow",
        "status": "warning",
        "backup": {"is_fresh": True},
        "journal": {"status": "ok", "created_task_ids": []},
        "bloat": {"status": "ok", "candidates": []},
        "actions_taken": [{"type": "vacuum_analyze", "scope": "summitflow", "fingerprint": "vacuum:summitflow:session_events", "status": "completed", "detail": "VACUUM ANALYZE session_events"}],
        "unresolved_issue_count": 1,
        "created_task_ids": ["task-project"],
        "reused_task_ids": [],
    }
    record_run = mocker.patch("app.tasks.runtime_hygiene.maintenance_store.record_maintenance_run")
    mocker.patch("app.tasks.runtime_hygiene._latest_runtime_hygiene_run", return_value=None)
    mocker.patch("app.tasks.runtime_hygiene._backup_rows_by_source", return_value={})
    mocker.patch(
        "app.tasks.runtime_hygiene._host_pressure",
        return_value=(host, [], [], [], []),
    )
    mocker.patch(
        "app.tasks.runtime_hygiene._infrastructure_protection",
        return_value=({"status": "ok", "backup": {"is_fresh": True}}, [], [], []),
    )
    mocker.patch(
        "app.tasks.runtime_hygiene._project_target",
        side_effect=[
            (target_summary, [{"scope": "summitflow", "issue_type": "db_bloat", "severity": "warning", "summary": "summitflow table session_events still shows actionable DB bloat", "fingerprint": "session_events", "task_id": "task-project"}], ["task-project"], []),
            ({
                "project_id": "agent-hub",
                "status": "ok",
                "backup": {"is_fresh": True},
                "journal": {"status": "ok", "created_task_ids": []},
                "bloat": {"status": "ok", "candidates": []},
                "actions_taken": [],
                "unresolved_issue_count": 0,
                "created_task_ids": [],
                "reused_task_ids": [],
            }, [], [], []),
        ],
    )

    result = run_runtime_hygiene()

    assert result["status"] == "partial"
    assert result["created_task_ids"] == ["task-project"]
    assert result["targets"]["summitflow"]["status"] == "warning"
    assert result["unresolved_issues"][0]["task_id"] == "task-project"
    record_run.assert_called_once()
    assert record_run.call_args.args[:2] == ("runtime_hygiene", "partial")
    assert record_run.call_args.kwargs["summary"]["targets"]["summitflow"]["status"] == "warning"
