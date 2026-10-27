"""Port detection fallbacks."""

from __future__ import annotations

from unittest.mock import patch

from app.services.project_index.port_detection import (
    extract_port_from_service_content,
    get_services,
)

_MODULE = "app.services.project_index.port_detection"


def test_get_services_prefers_manifest_ports_when_systemd_is_variable_based() -> None:
    with (
        patch(f"{_MODULE}.get_port_from_systemd", side_effect=[None, None]),
        patch(
            f"{_MODULE}.get_project_config",
            return_value={"root_path": "/srv/workspaces/projects/a-term", "backend_port": 8000, "frontend_port": 3002},
        ),
        patch(f"{_MODULE}.get_project_identity", return_value={"runtime": {"backend_port": 8002, "frontend_port": 3002}}),
        patch(f"{_MODULE}.sync_ports_to_db") as mock_sync,
    ):
        services = get_services("a-term")

    assert services == {"backend_port": 8002, "frontend_port": 3002}
    mock_sync.assert_called_once_with("a-term", 8002, None)


def test_get_services_keeps_systemd_ports_over_manifest_ports() -> None:
    with (
        patch(f"{_MODULE}.get_port_from_systemd", side_effect=[8010, 3010]),
        patch(
            f"{_MODULE}.get_project_config",
            return_value={"root_path": "/srv/workspaces/projects/a-term", "backend_port": 8002, "frontend_port": 3002},
        ),
        patch(f"{_MODULE}.get_project_identity", return_value={"runtime": {"backend_port": 8002, "frontend_port": 3002}}),
        patch(f"{_MODULE}.sync_ports_to_db") as mock_sync,
    ):
        services = get_services("a-term")

    assert services == {"backend_port": 8010, "frontend_port": 3010}
    mock_sync.assert_called_once_with("a-term", 8010, 3010)


def test_extract_port_accepts_shell_defaults_and_rejects_host_port_values() -> None:
    assert extract_port_from_service_content('ExecStart=uvicorn --port "${AGENT_HUB_PORT:-8003}"') == 8003
    assert extract_port_from_service_content("Environment=PORT=3001") == 3001
    assert extract_port_from_service_content("Environment=HATCHET_CLIENT_HOST_PORT=127.0.0.1:7070") is None
