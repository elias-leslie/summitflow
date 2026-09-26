"""Live collector failure state survives a tight status response budget."""

from monitor_control import MonitorControlError, enrich_status
from monitor_reader import encode_budgeted_json


def test_writer_failure_survives_status_compaction(monkeypatch) -> None:
    monkeypatch.setattr("monitor_control.control_request", lambda _command: {
        "ok": True, "writer_failure": "disk error", "policy_error": None,
        "detail_active": False, "active_leases": 0, "storage_bytes": 1,
        "collector_version": "0.1.0",
    })
    payload = {"schema": 1, "generated_at": "2026-09-26T00:00:00Z",
               "requested": {"kind": "status"}, "coverage": {},
               "items": [{"host": {"large": "x" * 4096}}],
               "next_cursor": None, "truncated": False, "errors": []}
    result = enrich_status(payload, 512)
    assert result["coverage"]["collector"] == {"availability": "error", "writer_failure": True}
    assert result["truncated"] is True
    assert len(encode_budgeted_json(result, 512).encode()) <= 512


def test_stopped_collector_survives_minimum_budget(monkeypatch) -> None:
    def unavailable(_command):
        raise MonitorControlError("stopped")
    monkeypatch.setattr("monitor_control.control_request", unavailable)
    payload = {"schema": 1, "generated_at": "2026-09-26T00:00:00Z",
               "requested": {"kind": "status"}, "coverage": {},
               "items": [{"large": "x" * 4096}], "next_cursor": None,
               "truncated": False, "errors": []}
    result = enrich_status(payload, 256)
    assert result["coverage"]["collector"]["availability"] == "collector_stopped"
    assert len(encode_budgeted_json(result, 256).encode()) <= 256
