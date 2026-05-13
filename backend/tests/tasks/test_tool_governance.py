from __future__ import annotations

from unittest.mock import Mock


def test_run_tool_governance_scan_records_summary(monkeypatch) -> None:
    from app.tasks.tool_governance import run_tool_governance_scan

    adoption = {
        "summary": {
            "shell_tool_events": 10,
            "st_commands": 7,
            "st_command_rate": 70.0,
            "raw_quality_commands": 0,
        }
    }
    audit = {
        "window_hours": 24,
        "summary": {"finding_groups": 1, "events": 3},
        "findings": [],
    }
    cost = {
        "manifest_costs": [
            {"density": "core", "tokens_approx": 100},
            {"density": "full", "tokens_approx": 700},
        ],
        "request_hotspots": [{"tool_name": "sdk.complete"}],
        "tool_output_hotspots": [{"tool_name": "Bash"}],
    }
    emit_audit = Mock()
    emit_cost = Mock()
    record = Mock()

    monkeypatch.setattr("cli.commands.tools._fetch_adoption_metrics", lambda hours, limit: adoption)
    monkeypatch.setattr("cli.commands.tools._fetch_audit_metrics", lambda hours, limit: audit)
    monkeypatch.setattr("cli.commands.tools._fetch_cost_metrics", lambda hours, limit: cost)
    monkeypatch.setattr("cli.commands.tools._emit_feedback_for_audit", emit_audit)
    monkeypatch.setattr("cli.commands.tools._emit_feedback_for_cost", emit_cost)
    monkeypatch.setattr("app.tasks.tool_governance.maintenance_store.record_maintenance_run", record)

    result = run_tool_governance_scan(hours=24, limit=20)

    assert result["status"] == "completed"
    assert result["st_command_rate"] == 70.0
    assert result["audit_events"] == 3
    assert result["manifest_saved_tokens_approx"] == 600
    emit_audit.assert_called_once_with(audit)
    emit_cost.assert_called_once_with(cost)
    assert record.call_args.args[:2] == ("tool_governance", "completed")
    assert record.call_args.kwargs["rows_cleaned"] == 3


def test_run_tool_governance_scan_records_feedback_errors(monkeypatch) -> None:
    from app.tasks.tool_governance import run_tool_governance_scan

    monkeypatch.setattr(
        "cli.commands.tools._fetch_adoption_metrics",
        lambda hours, limit: {"summary": {}},
    )
    monkeypatch.setattr(
        "cli.commands.tools._fetch_audit_metrics",
        lambda hours, limit: {"window_hours": hours, "summary": {"finding_groups": 0, "events": 0}},
    )
    monkeypatch.setattr(
        "cli.commands.tools._fetch_cost_metrics",
        lambda hours, limit: {"manifest_costs": [], "request_hotspots": [], "tool_output_hotspots": []},
    )
    monkeypatch.setattr("cli.commands.tools._emit_feedback_for_audit", Mock(side_effect=RuntimeError("feedback down")))
    monkeypatch.setattr("cli.commands.tools._emit_feedback_for_cost", Mock())
    record = Mock()
    monkeypatch.setattr("app.tasks.tool_governance.maintenance_store.record_maintenance_run", record)

    result = run_tool_governance_scan()

    assert result["status"] == "partial"
    assert result["feedback_errors"] == [{"source": "audit", "error": "feedback down"}]
    assert record.call_args.args[:2] == ("tool_governance", "partial")
    assert record.call_args.kwargs["error_message"] == "feedback down"
