from __future__ import annotations

from unittest.mock import patch

from app.tasks.explorer_tasks import scan_all_projects


def test_scan_all_projects_reports_duration_and_project_details() -> None:
    with (
        patch(
            "app.tasks.explorer_tasks._fetch_projects",
            return_value=[
                ("project-1", "Project One", "/tmp/project-1"),
                ("project-2", "Project Two", "/tmp/project-2"),
            ],
        ),
        patch(
            "app.tasks.explorer_tasks.explorer.run_scan_job",
            return_value={
                "scan_id": 11,
                "results": [{"entry_type": "file"}],
                "metrics": {"complexity": 123},
            },
        ),
        patch("app.tasks.explorer_tasks.time.sleep"),
    ):
        result = scan_all_projects(entry_type="file", dry_run=False, dispatch=None)

    assert result["status"] == "success"
    assert result["scanned"] == 2
    assert result["errors"] == 0
    assert result["duration_ms"] >= 0
    assert len(result["details"]) == 2
    assert result["details"][0]["scan_id"] == 11
    assert result["details"][0]["metrics"] == {"complexity": 123}
    assert result["details"][0]["duration_ms"] >= 0
    assert result["details"][1]["duration_ms"] >= 0


def test_scan_all_projects_reports_error_duration() -> None:
    with (
        patch(
            "app.tasks.explorer_tasks._fetch_projects",
            return_value=[("project-1", "Project One", "/tmp/project-1")],
        ),
        patch(
            "app.tasks.explorer_tasks.explorer.run_scan_job",
            side_effect=RuntimeError("boom"),
        ),
    ):
        result = scan_all_projects(entry_type="file", dry_run=False, dispatch=None)

    assert result["status"] == "partial"
    assert result["scanned"] == 0
    assert result["errors"] == 1
    assert result["duration_ms"] >= 0
    assert result["details"][0]["status"] == "error"
    assert result["details"][0]["duration_ms"] >= 0


def test_scan_all_projects_logs_post_scan_dispatch_failure_without_failing_scan(mocker) -> None:
    dispatch = mocker.Mock(side_effect=RuntimeError("missing target"))
    logger = mocker.patch("app.tasks.explorer_tasks.logger")

    with (
        patch(
            "app.tasks.explorer_tasks._fetch_projects",
            return_value=[("project-1", "Project One", "/tmp/project-1")],
        ),
        patch(
            "app.tasks.explorer_tasks.explorer.run_scan_job",
            return_value={
                "scan_id": 11,
                "results": [{"entry_type": "file"}],
                "metrics": {"complexity": 123},
            },
        ),
    ):
        result = scan_all_projects(entry_type="file", dry_run=False, dispatch=dispatch)

    assert result["status"] == "success"
    assert result["scanned"] == 1
    logger.exception.assert_called_once_with("post_scan_dispatch_failed", project_id="project-1")
