from fastapi.testclient import TestClient

from app.api.backups import native_host_endpoints as endpoint
from app.main import app


def test_native_host_route_preserves_pending_qualification(monkeypatch):
    payload = {
        "engine": "btrbk", "installed": True, "configured": False,
        "enabled": False, "ready": False, "last_result": None,
        "blocked_reason": "Native destination awaits storage cutover",
        "windows_method": "Veeam",
    }
    monkeypatch.setattr(endpoint, "native_host_status", lambda: payload)
    response = TestClient(app).get("/api/backups/native-host")
    assert response.status_code == 200
    assert response.json() == payload


def test_native_host_status_has_no_http_capture_action():
    assert TestClient(app).post("/api/backups/native-host").status_code == 405
