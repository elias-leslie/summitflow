"""Tests for Explorer port detection fallbacks."""

from __future__ import annotations

from unittest.mock import patch

from app.services.explorer.port_detection import get_services


def test_get_services_prefers_manifest_ports_when_systemd_is_variable_based() -> None:
    with (
        patch(
            "app.services.explorer.port_detection.get_port_from_systemd",
            side_effect=[None, None],
        ),
        patch(
            "app.services.explorer.base.get_project_config",
            return_value={
                "root_path": "/srv/workspaces/projects/a-term",
                "backend_port": 8000,
                "frontend_port": 3002,
            },
        ),
        patch(
            "app.services.explorer.port_detection.get_project_identity",
            return_value={
                "runtime": {
                    "backend_port": 8002,
                    "frontend_port": 3002,
                }
            },
        ),
        patch("app.services.explorer.port_detection.sync_ports_to_db") as mock_sync,
    ):
        services = get_services("a-term")

    assert services["backend_port"] == 8002
    assert services["frontend_port"] == 3002
    mock_sync.assert_called_once_with("a-term", 8002, None)


def test_get_services_keeps_systemd_ports_over_manifest_ports() -> None:
    with (
        patch(
            "app.services.explorer.port_detection.get_port_from_systemd",
            side_effect=[8010, 3010],
        ),
        patch(
            "app.services.explorer.base.get_project_config",
            return_value={
                "root_path": "/srv/workspaces/projects/a-term",
                "backend_port": 8002,
                "frontend_port": 3002,
            },
        ),
        patch(
            "app.services.explorer.port_detection.get_project_identity",
            return_value={
                "runtime": {
                    "backend_port": 8002,
                    "frontend_port": 3002,
                }
            },
        ),
        patch("app.services.explorer.port_detection.sync_ports_to_db") as mock_sync,
    ):
        services = get_services("a-term")

    assert services["backend_port"] == 8010
    assert services["frontend_port"] == 3010
    mock_sync.assert_called_once_with("a-term", 8010, 3010)
