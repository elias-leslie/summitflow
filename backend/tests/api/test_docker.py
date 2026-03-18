"""Tests for Docker management API endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.main import app

client = TestClient(app)


def _status(
    *,
    name: str,
    service: str,
    manager: str,
    category: str,
    state: str,
    health: str = "",
    status: str | None = None,
    ports: list[str] | None = None,
):
    from app.api import docker as docker_api

    return docker_api.RuntimeServiceStatus(
        name=name,
        service=service,
        display_name=service,
        manager=manager,
        category=category,
        state=state,
        health=health,
        status=status or state,
        ports=ports or [],
    )


class TestDockerRuntime:
    """Tests for Docker runtime mode endpoints."""

    def test_detect_repo_root_walks_up_container_layout(self, tmp_path) -> None:
        from app.api import docker as docker_api

        repo_root = tmp_path / "repo"
        script_path = repo_root / "scripts" / "rebuild.sh"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/bin/bash\n")

        module_path = repo_root / "app" / "api" / "docker.py"
        module_path.parent.mkdir(parents=True)
        module_path.write_text("# test\n")

        assert docker_api._detect_repo_root(module_path) == repo_root

    def test_rebuild_script_prefers_host_repo_root(self, mocker: MockerFixture, tmp_path) -> None:
        from app.api import docker as docker_api

        host_repo_root = tmp_path / "summitflow"
        script_path = host_repo_root / "scripts" / "rebuild.sh"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/bin/bash\n")

        mocker.patch.object(docker_api, "_HOST_REPO_ROOT", host_repo_root)
        mocker.patch.object(docker_api, "_HOST_HOME_PATH", tmp_path)
        mocker.patch.object(docker_api, "_REPO_ROOT", Path("/app"))

        assert docker_api._rebuild_script_path() == script_path

    def test_launch_runtime_switch_adds_socket_group(
        self,
        mocker: MockerFixture,
        tmp_path,
    ) -> None:
        from app.api import docker as docker_api

        script_path = tmp_path / "summitflow" / "scripts" / "rebuild.sh"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/bin/bash\n")

        docker_socket = tmp_path / "docker.sock"
        docker_socket.write_text("")

        mocker.patch.object(docker_api, "_DOCKER_SOCKET", docker_socket)
        mocker.patch.object(docker_api, "_HOST_HOME_PATH", tmp_path)
        mocker.patch.object(docker_api, "COMPOSE_PROJECT", "summitflow-stack")
        mocker.patch.object(
            docker_api,
            "_helper_image_ref",
            new=mocker.AsyncMock(return_value="ghcr.io/summitflow-solutions/summitflow-api:test"),
        )
        run_docker = mocker.patch.object(
            docker_api,
            "_run_docker",
            new=mocker.AsyncMock(side_effect=[("", "", 0), ("helper-id\n", "", 0)]),
        )

        helper_name = asyncio.run(docker_api._launch_runtime_switch("dev", script_path))

        assert helper_name == "summitflow-stack-mode-switch"
        run_args = run_docker.await_args_list[1].args
        assert "--entrypoint" in run_args
        assert "--group-add" in run_args
        assert "--network" in run_args
        assert "host" in run_args
        assert str(docker_socket.stat().st_gid) in run_args

    def test_runtime_status_prefers_detected_running_mode(
        self,
        mocker: MockerFixture,
        tmp_path,
    ) -> None:
        from app.api import docker as docker_api

        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        compose_file = compose_dir / "docker-compose.yml"
        compose_file.write_text("services: {}\n")
        runtime_file = compose_dir / ".runtime-mode"
        runtime_file.write_text("prod\n")

        mocker.patch.object(docker_api, "_COMPOSE_FILE", compose_file)
        mocker.patch.object(docker_api, "_RUNTIME_MODE_FILE", runtime_file)
        mocker.patch.object(docker_api, "_DEFAULT_STACK_MODE", "dev")
        mocker.patch.object(
            docker_api,
            "_runtime_service_statuses",
            new=mocker.AsyncMock(
                return_value=[
                    _status(
                        name="summitflow-backend.service",
                        service="summitflow-api",
                        manager="systemd",
                        category="app",
                        state="stopped",
                    )
                ]
            ),
        )
        mocker.patch.object(
            docker_api,
            "_project_containers",
            new=mocker.AsyncMock(
                return_value=[
                    {
                        "ID": "abc123",
                        "Labels": "com.docker.compose.service=summitflow-api",
                    }
                ]
            ),
        )
        mocker.patch.object(
            docker_api,
            "_detect_running_mode",
            new=mocker.AsyncMock(return_value="dev"),
        )

        response = client.get("/api/docker/runtime")

        assert response.status_code == 200
        assert response.json() == {
            "runtime": "docker",
            "apps_runtime": "docker",
            "infra_runtime": "stopped",
            "current_mode": "dev",
            "configured_mode": "prod",
            "default_mode": "dev",
            "source": "detected",
            "is_running": True,
        }

    def test_runtime_status_falls_back_to_default_when_no_stack_running(
        self,
        mocker: MockerFixture,
        tmp_path,
    ) -> None:
        from app.api import docker as docker_api

        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        compose_file = compose_dir / "docker-compose.yml"
        compose_file.write_text("services: {}\n")
        runtime_file = compose_dir / ".runtime-mode"

        mocker.patch.object(docker_api, "_COMPOSE_FILE", compose_file)
        mocker.patch.object(docker_api, "_RUNTIME_MODE_FILE", runtime_file)
        mocker.patch.object(docker_api, "_DEFAULT_STACK_MODE", "dev")
        mocker.patch.object(
            docker_api,
            "_runtime_service_statuses",
            new=mocker.AsyncMock(return_value=[]),
        )
        mocker.patch.object(
            docker_api,
            "_project_containers",
            new=mocker.AsyncMock(return_value=[]),
        )

        response = client.get("/api/docker/runtime")

        assert response.status_code == 200
        assert response.json() == {
            "runtime": "docker-stopped",
            "apps_runtime": "stopped",
            "infra_runtime": "stopped",
            "current_mode": "dev",
            "configured_mode": "dev",
            "default_mode": "dev",
            "source": "default",
            "is_running": False,
        }

    def test_runtime_mode_switch_uses_detached_helper(
        self,
        mocker: MockerFixture,
        tmp_path,
    ) -> None:
        from app.api import docker as docker_api

        script_path = tmp_path / "rebuild.sh"
        script_path.write_text("#!/bin/bash\n")

        mocker.patch.object(docker_api, "_rebuild_script_path", return_value=script_path)
        mocker.patch.object(docker_api, "_INTERNAL_SECRET", "")
        mocker.patch.object(
            docker_api,
            "_get_runtime_status",
            new=mocker.AsyncMock(
                return_value=docker_api.RuntimeModeStatus(
                    runtime="docker",
                    apps_runtime="docker",
                    infra_runtime="docker",
                    current_mode="prod",
                    configured_mode="prod",
                    default_mode="dev",
                    source="persisted",
                    is_running=True,
                )
            ),
        )
        launch_switch = mocker.patch.object(
            docker_api,
            "_launch_runtime_switch",
            new=mocker.AsyncMock(return_value="summitflow-stack-mode-switch"),
        )

        response = client.post("/api/docker/runtime", json={"mode": "dev"})

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Queued Docker stack switch to dev mode via summitflow-stack-mode-switch",
        }
        launch_switch.assert_awaited_once_with("dev", script_path)

    def test_runtime_mode_switch_persists_preference_for_hybrid_runtime(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        mocker.patch.object(docker_api, "_INTERNAL_SECRET", "")
        mocker.patch.object(
            docker_api,
            "_get_runtime_status",
            new=mocker.AsyncMock(
                return_value=docker_api.RuntimeModeStatus(
                    runtime="hybrid",
                    apps_runtime="native",
                    infra_runtime="docker",
                    current_mode="dev",
                    configured_mode="dev",
                    default_mode="dev",
                    source="persisted",
                    is_running=True,
                )
            ),
        )
        write_mode = mocker.patch.object(docker_api, "_write_runtime_mode")
        launch_switch = mocker.patch.object(
            docker_api,
            "_launch_runtime_switch",
            new=mocker.AsyncMock(),
        )

        response = client.post("/api/docker/runtime", json={"mode": "prod"})

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Saved Docker parity preference: prod. Live services remain native apps with Docker infra.",
        }
        write_mode.assert_called_once_with("prod")
        launch_switch.assert_not_called()

    def test_restart_service_clears_native_ports_before_start(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        mocker.patch.object(
            docker_api,
            "_run_systemctl_user",
            new=mocker.AsyncMock(
                side_effect=[
                    ("", "", 0),
                    ("", "", 0),
                ]
            ),
        )
        clear_ports = mocker.patch.object(
            docker_api,
            "_clear_service_ports",
            new=mocker.AsyncMock(),
        )

        result = asyncio.run(docker_api._service_action("summitflow-api", "restart"))

        assert result == docker_api.ActionResult(
            success=True,
            message="Restarted summitflow-api",
        )
        clear_ports.assert_awaited_once()

    def test_systemd_unit_state_marks_timeouts_as_unknown(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        mocker.patch.object(
            docker_api,
            "_run_systemctl_user",
            new=mocker.AsyncMock(return_value=("", "Timed out after 0.75s", 124)),
        )

        result = asyncio.run(docker_api._systemd_unit_state("summitflow-backend.service"))

        assert result == {
            "Id": "summitflow-backend.service",
            "LoadState": "unknown",
            "ActiveState": "unknown",
            "SubState": "timed-out",
            "MainPID": "0",
            "ExecMainStatus": "0",
            "Error": "Timed out after 0.75s",
        }

    def test_runtime_service_status_uses_http_probe_when_systemctl_is_unavailable(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        mocker.patch.object(
            docker_api,
            "_systemd_unit_state",
            new=mocker.AsyncMock(
                return_value={
                    "Id": "summitflow-backend.service",
                    "LoadState": "unknown",
                    "ActiveState": "unknown",
                    "SubState": "timed-out",
                    "MainPID": "0",
                    "ExecMainStatus": "0",
                }
            ),
        )
        mocker.patch.object(
            docker_api,
            "_probe_http",
            new=mocker.AsyncMock(return_value=(True, 200)),
        )

        result = asyncio.run(
            docker_api._runtime_service_status(
                docker_api._RUNTIME_SERVICE_MAP["summitflow-api"],
                {},
            )
        )

        assert result == docker_api.RuntimeServiceStatus(
            name="summitflow-backend.service",
            service="summitflow-api",
            display_name="summitflow-api",
            manager="systemd",
            category="app",
            state="running",
            health="healthy",
            status="Serving HTTP 200",
            ports=["8001"],
        )

    def test_proxmox_status_returns_unconfigured_when_env_is_missing(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import _runtime_proxmox

        mocker.patch.object(
            _runtime_proxmox,
            "_proxmox_config",
            return_value={
                "api_url": "",
                "token_id": "",
                "token_secret": "",
                "verify_ssl": False,
            },
        )

        response = client.get("/api/docker/proxmox")

        assert response.status_code == 200
        assert response.json() == {
            "configured": False,
            "reachable": False,
            "api_url": None,
            "error": "Set PROXMOX_API_URL, PROXMOX_TOKEN_ID, and PROXMOX_TOKEN_SECRET to enable Proxmox status.",
            "nodes": [],
            "guests": [],
        }

    def test_proxmox_status_lists_nodes_and_guests(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import _runtime_proxmox

        mocker.patch.object(
            _runtime_proxmox,
            "_proxmox_config",
            return_value={
                "api_url": "https://192.168.8.233:8006",
                "token_id": "root@pam!automation",
                "token_secret": "secret",
                "verify_ssl": False,
            },
        )
        mocker.patch.object(
            _runtime_proxmox,
            "_sync_proxmox_get_json",
            side_effect=[
                [
                    {
                        "node": "davion-gem",
                        "status": "online",
                        "cpu": 0.125,
                        "mem": 8589934592,
                        "maxmem": 17179869184,
                        "uptime": 1234,
                    }
                ],
                [
                    {
                        "vmid": 100,
                        "name": "test-vm",
                        "node": "davion-gem",
                        "type": "qemu",
                        "status": "running",
                        "cpu": 0.25,
                        "mem": 4294967296,
                        "maxmem": 8589934592,
                        "uptime": 5678,
                        "tags": "test;browser",
                    }
                ],
            ],
        )

        response = client.get("/api/docker/proxmox")

        assert response.status_code == 200
        assert response.json() == {
            "configured": True,
            "reachable": True,
            "api_url": "https://192.168.8.233:8006",
            "error": None,
            "nodes": [
                {
                    "node": "davion-gem",
                    "status": "online",
                    "cpu_percent": 12.5,
                    "memory_used_bytes": 8589934592,
                    "memory_total_bytes": 17179869184,
                    "uptime_seconds": 1234,
                }
            ],
            "guests": [
                {
                    "vmid": 100,
                    "name": "test-vm",
                    "node": "davion-gem",
                    "type": "qemu",
                    "status": "running",
                    "cpu_percent": 25.0,
                    "memory_used_bytes": 4294967296,
                    "memory_total_bytes": 8589934592,
                    "uptime_seconds": 5678,
                    "tags": ["test", "browser"],
                }
            ],
        }
