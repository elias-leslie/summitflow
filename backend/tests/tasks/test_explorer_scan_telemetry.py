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
        patch("app.tasks.explorer_tasks.scan_project", return_value=[{"type": "file"}]),
        patch("app.tasks.explorer_tasks.time.sleep"),
    ):
        result = scan_all_projects(entry_type="file", dry_run=False, dispatch=None)

    assert result["status"] == "success"
    assert result["scanned"] == 2
    assert result["errors"] == 0
    assert result["duration_ms"] >= 0
    assert len(result["details"]) == 2
    assert result["details"][0]["duration_ms"] >= 0
    assert result["details"][1]["duration_ms"] >= 0


def test_scan_all_projects_reports_error_duration() -> None:
    with (
        patch(
            "app.tasks.explorer_tasks._fetch_projects",
            return_value=[("project-1", "Project One", "/tmp/project-1")],
        ),
        patch("app.tasks.explorer_tasks.scan_project", side_effect=RuntimeError("boom")),
    ):
        result = scan_all_projects(entry_type="file", dry_run=False, dispatch=None)

    assert result["status"] == "partial"
    assert result["scanned"] == 0
    assert result["errors"] == 1
    assert result["duration_ms"] >= 0
    assert result["details"][0]["status"] == "error"
    assert result["details"][0]["duration_ms"] >= 0

