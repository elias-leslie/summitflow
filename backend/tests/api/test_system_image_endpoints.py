from fastapi.testclient import TestClient

from app.api.backups import system_image_endpoints as endpoint
from app.main import app


def test_system_image_status_reports_secure_boot_pending(monkeypatch):
    monkeypatch.setattr(endpoint, "_installed_version", lambda: "6.3.2.1307")
    monkeypatch.setattr(endpoint, "_service_active", lambda: True)
    monkeypatch.setattr(endpoint, "_secure_boot_enabled", lambda: True)
    monkeypatch.setattr(endpoint, "_mok_enrolled", lambda: False)
    monkeypatch.setattr(endpoint, "_mok_enrollment_pending", lambda: True)
    monkeypatch.setattr(endpoint, "_module_loaded", lambda: False)
    monkeypatch.setattr(endpoint, "_module_signer", lambda: "test signer")
    monkeypatch.setattr(endpoint, "_repository_status", lambda: (True, True))
    monkeypatch.setattr(
        endpoint,
        "_job_info",
        lambda: (True, "job-1", "Daily at 02:00", ["/dev/nvme0n1p7"]),
    )
    monkeypatch.setattr(endpoint, "_sessions", lambda: [])

    client = TestClient(app)
    response = client.get("/api/backups/system-image")

    assert response.status_code == 200
    payload = response.json()
    assert payload["installed"] is True
    assert payload["can_start"] is False
    assert payload["mok_enrollment_pending"] is True
    assert payload["blocked_reason"] == "Secure Boot is waiting for MOK enrollment at next reboot."


def test_system_image_start_rejects_when_blocked(monkeypatch):
    monkeypatch.setattr(
        endpoint,
        "_status_sync",
        lambda: endpoint.SystemImageBackupStatus(
            installed=True,
            version="6.3.2.1307",
            service_active=True,
            secure_boot_enabled=True,
            mok_enrolled=False,
            mok_enrollment_pending=True,
            module_loaded=False,
            module_signer="test signer",
            repository_name=endpoint.REPOSITORY_NAME,
            repository_path=endpoint.REPOSITORY_PATH,
            repository_accessible=True,
            job_name=endpoint.JOB_NAME,
            job_configured=True,
            job_id="job-1",
            schedule_summary="Daily at 02:00",
            protected_objects=["/dev/nvme0n1p7"],
            last_session=None,
            active_session=None,
            can_start=False,
            blocked_reason="Secure Boot is waiting for MOK enrollment at next reboot.",
            next_action="Secure Boot is waiting for MOK enrollment at next reboot.",
        ),
    )

    client = TestClient(app)
    response = client.post("/api/backups/system-image/start")

    assert response.status_code == 409
    assert "Secure Boot is waiting for MOK enrollment at next reboot." in str(response.json())
