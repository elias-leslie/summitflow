"""No recorded quality checks is unknown, never an all-green empty set."""
from unittest.mock import MagicMock

from app.storage import quality_check_results as quality


def test_empty_single_project_health_is_not_green(monkeypatch):
    monkeypatch.setattr(quality, "fetch_health_data", lambda *_args: ([], {}))
    summary = quality.get_project_health_summary(MagicMock(), "empty")
    assert summary["overall_pass"] is False and summary["evidence_state"] == "unknown"


def test_bulk_empty_projects_stay_unknown_without_hiding_recorded_pass():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.side_effect = [
        [("observed", "ruff", "pass", 0, 0)], [],
    ]
    summaries = quality.get_projects_health_summaries(conn, ["empty", "observed"])
    assert summaries["empty"]["overall_pass"] is False
    assert summaries["empty"]["evidence_state"] == "unknown"
    assert summaries["observed"]["overall_pass"] is True


def test_bulk_failure_is_not_overwritten_by_later_pass():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.side_effect = [
        [("observed", "ruff", "fail", 1, 0), ("observed", "pytest", "pass", 0, 0)], [],
    ]
    assert quality.get_projects_health_summaries(conn, ["observed"])["observed"]["overall_pass"] is False
