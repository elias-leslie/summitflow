from fastapi.testclient import TestClient

from app.api.backups import destinations_endpoints as endpoint
from app.main import app


def test_destinations_reads_checks_and_proxmox_copy(monkeypatch):
    status = {"sections": {
        "restic_checks": {"checks": {"local": {"checked_at": "2026-10-24T06:45:00+00:00", "status": "verified", "bucket": 18},
                                     "remote": {"checked_at": "2026-10-24T08:43:00+00:00", "status": "verified"}},
                          "alerts": [{"kind": "stale", "message": "Drive check overdue"}]},
        "pve_copy": {"last_success_at": "2026-10-24T12:42:00+00:00", "last_attempt_at": "2026-10-24T12:41:00+00:00",
                     "pve_maintenance": {"check": {"checked_at": "2026-10-18T05:36:00+00:00", "status": "verified"}},
                     "alerts": []},
    }}
    monkeypatch.setattr(endpoint, "read_status", lambda: status)
    monkeypatch.setattr(endpoint.settings, "backup_schedule_window", "02:00-06:00")

    body = TestClient(app).get("/api/backups/destinations").json()

    assert body["schedule_window"] == "02:00-06:00"
    assert body["local_check"] == {"checked_at": "2026-10-24T06:45:00+00:00", "status": "verified"}
    assert body["drive_check"]["status"] == "verified"
    assert body["check_alerts"] == ["Drive check overdue"]
    assert body["proxmox"] == {"last_copy_at": "2026-10-24T12:42:00+00:00", "last_attempt_at": "2026-10-24T12:41:00+00:00",
                               "error": None, "checked_at": "2026-10-18T05:36:00+00:00", "check_status": "verified", "alerts": []}


def test_destinations_without_records_reports_nothing_checked(monkeypatch):
    monkeypatch.setattr(endpoint, "read_status", lambda: {})

    body = TestClient(app).get("/api/backups/destinations").json()

    assert body["local_check"] is None
    assert body["drive_check"] is None
    assert body["proxmox"] is None
