"""Tests for Docker management API endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.main import app

client = TestClient(app)


def _status(
    *,
    name: str,
    service: str,
    manager: Literal["docker", "systemd"],
    category: Literal["app", "worker", "infra"],
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

    def test_runtime_service_map_includes_registered_native_projects(self) -> None:
        from app.api import docker as docker_api

        assert docker_api._RUNTIME_SERVICE_MAP["agent-hub-worker"]["unit"] == (
            "agent-hub-hatchet-agent-worker.service"
        )
        assert docker_api._RUNTIME_SERVICE_MAP["agent-hub-ops-worker"]["unit"] == (
            "agent-hub-hatchet-ops-worker.service"
        )
        assert docker_api._RUNTIME_SERVICE_MAP["vantage-api"]["unit"] == "vantage-backend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["vantage-web"]["unit"] == "vantage-frontend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["vantage-worker"]["unit"] == (
            "vantage-hatchet-worker.service"
        )
        assert docker_api._RUNTIME_SERVICE_MAP["test1-api"]["unit"] == "test1-backend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["test1-web"]["unit"] == "test1-frontend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["test2-api"]["unit"] == "test2-backend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["test2-web"]["unit"] == "test2-frontend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["test3-api"]["unit"] == "test3-backend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["test3-web"]["unit"] == "test3-frontend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["sha-api"]["unit"] == "sha-backend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["sha-web"]["unit"] == "sha-frontend.service"
        assert docker_api._RUNTIME_SERVICE_MAP["hermes-dashboard"]["unit"] == (
            "hermes-dashboard.service"
        )
        assert docker_api._RUNTIME_SERVICE_MAP["hermes-dashboard"]["ports"] == ["9119"]

    def test_detect_repo_root_walks_up_container_layout(self, tmp_path) -> None:
        from app.api import docker as docker_api

        repo_root = tmp_path / "repo"
        (repo_root / "backend" / "cli").mkdir(parents=True)
        (repo_root / "backend" / "app").mkdir(parents=True)

        module_path = repo_root / "app" / "api" / "docker.py"
        module_path.parent.mkdir(parents=True)
        module_path.write_text("# test\n")

        assert docker_api._detect_repo_root(module_path) == repo_root

    def test_st_cli_prefers_host_repo_root(self, mocker: MockerFixture, tmp_path) -> None:
        from app.api import docker as docker_api

        host_repo_root = tmp_path / "summitflow"
        st_path = host_repo_root / "backend" / ".venv" / "bin" / "st"
        st_path.parent.mkdir(parents=True)
        st_path.write_text("#!/bin/bash\n")

        mocker.patch("app.api.docker.helpers._HOST_REPO_ROOT", host_repo_root)
        mocker.patch("app.api.docker.helpers._HOST_HOME_PATH", tmp_path)
        mocker.patch("app.api.docker.helpers._REPO_ROOT", Path("/app"))

        assert docker_api._st_cli_path() == st_path

    def test_launch_runtime_switch_adds_socket_group(
        self,
        mocker: MockerFixture,
        tmp_path,
    ) -> None:
        from app.api import docker as docker_api

        st_path = tmp_path / "summitflow" / "backend" / ".venv" / "bin" / "st"
        st_path.parent.mkdir(parents=True)
        st_path.write_text("#!/bin/bash\n")

        docker_socket = tmp_path / "docker.sock"
        docker_socket.write_text("")

        mocker.patch("app.api.docker.helpers._DOCKER_SOCKET", docker_socket)
        mocker.patch("app.api.docker.helpers._HOST_HOME_PATH", tmp_path)
        mocker.patch("app.api.docker.helpers.COMPOSE_PROJECT", "summitflow-stack")
        mocker.patch(
            "app.api.docker.helpers._helper_image_ref",
            new=mocker.AsyncMock(return_value="ghcr.io/elias-leslie/summitflow-api:test"),
        )
        run_docker = mocker.patch(
            "app.api.docker.helpers._run_docker",
            new=mocker.AsyncMock(side_effect=[("", "", 0), ("helper-id\n", "", 0)]),
        )

        helper_name = asyncio.run(docker_api._launch_runtime_switch("dev", st_path))

        assert helper_name == "summitflow-stack-mode-switch"
        run_args = run_docker.await_args_list[1].args
        assert "--entrypoint" in run_args
        assert "--group-add" in run_args
        assert "--network" in run_args
        assert "host" in run_args
        assert str(docker_socket.stat().st_gid) in run_args
        assert "docker up --dev --detach" in run_args[-1]

    def test_runtime_status_prefers_detected_running_mode(
        self,
        mocker: MockerFixture,
        tmp_path,
    ) -> None:
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        compose_file = compose_dir / "docker-compose.yml"
        compose_file.write_text("services: {}\n")
        runtime_file = compose_dir / ".runtime-mode"
        runtime_file.write_text("prod\n")

        mocker.patch("app.api.docker.constants._COMPOSE_FILE", compose_file)
        mocker.patch("app.api.docker.constants._RUNTIME_MODE_FILE", runtime_file)
        mocker.patch("app.api.docker.constants._DEFAULT_STACK_MODE", "dev")
        mocker.patch(
            "app.api.docker.helpers._runtime_service_statuses",
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
        mocker.patch(
            "app.api.docker.helpers._project_containers",
            new=mocker.AsyncMock(
                return_value=[
                    {
                        "ID": "abc123",
                        "Labels": "com.docker.compose.service=summitflow-api",
                    }
                ]
            ),
        )
        mocker.patch(
            "app.api.docker.helpers._detect_running_mode",
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
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        compose_file = compose_dir / "docker-compose.yml"
        compose_file.write_text("services: {}\n")
        runtime_file = compose_dir / ".runtime-mode"

        mocker.patch("app.api.docker.constants._COMPOSE_FILE", compose_file)
        mocker.patch("app.api.docker.constants._RUNTIME_MODE_FILE", runtime_file)
        mocker.patch("app.api.docker.constants._DEFAULT_STACK_MODE", "dev")
        mocker.patch(
            "app.api.docker.helpers._runtime_service_statuses",
            new=mocker.AsyncMock(return_value=[]),
        )
        mocker.patch(
            "app.api.docker.helpers._project_containers",
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

        st_path = tmp_path / "st"
        st_path.write_text("#!/bin/bash\n")

        mocker.patch("app.api.docker.routes._st_cli_path", return_value=st_path)
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        mocker.patch(
            "app.api.docker.routes._get_runtime_status",
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
        launch_switch = mocker.patch(
            "app.api.docker.routes._launch_runtime_switch",
            new=mocker.AsyncMock(return_value="summitflow-stack-mode-switch"),
        )

        response = client.post("/api/docker/runtime", json={"mode": "dev"})

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Queued Docker stack switch to dev mode via summitflow-stack-mode-switch",
        }
        launch_switch.assert_awaited_once_with("dev", st_path)

    def test_runtime_mode_switch_persists_preference_for_hybrid_runtime(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        mocker.patch(
            "app.api.docker.routes._get_runtime_status",
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
        write_mode = mocker.patch("app.api.docker.routes._write_runtime_mode")
        launch_switch = mocker.patch(
            "app.api.docker.routes._launch_runtime_switch",
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

        mocker.patch(
            "app.api.docker.helpers._run_systemctl_user",
            new=mocker.AsyncMock(
                side_effect=[
                    ("", "", 0),
                    ("", "", 0),
                ]
            ),
        )
        clear_ports = mocker.patch(
            "app.api.docker.helpers._clear_service_ports",
            new=mocker.AsyncMock(),
        )

        result = asyncio.run(docker_api._service_action("summitflow-api", "restart"))

        assert result == docker_api.ActionResult(
            success=True,
            message="Restarted summitflow-api",
        )
        clear_ports.assert_awaited_once()

    def test_stop_api_service_stops_native_siblings_to_prevent_restart(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        run_systemctl = mocker.patch(
            "app.api.docker.helpers._run_systemctl_user",
            new=mocker.AsyncMock(return_value=("", "", 0)),
        )
        clear_ports = mocker.patch(
            "app.api.docker.helpers._clear_service_ports",
            new=mocker.AsyncMock(),
        )

        result = asyncio.run(docker_api._service_action("vantage-api", "stop"))

        assert result == docker_api.ActionResult(
            success=True,
            message="Stopped vantage-api",
        )
        run_systemctl.assert_awaited_once_with(
            "stop",
            "vantage-frontend.service",
            "vantage-hatchet-worker.service",
            "vantage-backend.service",
            timeout=docker_api._COMMAND_TIMEOUT_SECONDS,
        )
        assert [call.args[0]["service"] for call in clear_ports.await_args_list] == [
            "vantage-web",
            "vantage-worker",
            "vantage-api",
        ]

    def test_systemd_unit_state_marks_timeouts_as_unknown(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        mocker.patch(
            "app.api.docker.helpers._run_systemctl_user",
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

        mocker.patch(
            "app.api.docker.helpers._systemd_unit_state",
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
        mocker.patch(
            "app.api.docker.helpers._probe_http",
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

    def test_metrics_history_returns_persisted_series(
        self,
        mocker: MockerFixture,
    ) -> None:
        from datetime import UTC, datetime

        list_series = mocker.patch(
            "app.api.docker.routes.runtime_metric_store.list_runtime_metric_series",
            return_value=[
                {
                    "service": "summitflow-api",
                    "display_name": "summitflow-api",
                    "manager": "systemd",
                    "category": "app",
                    "samples": [
                        {
                            "sampled_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                            "sample_count": 1,
                            "state": "running",
                            "status": "active",
                            "cpu_percent": 3.5,
                            "cpu_percent_max": 3.5,
                            "memory_percent": 5.8,
                            "memory_percent_max": 5.8,
                            "memory_used_bytes": 125829120,
                            "memory_used_bytes_max": 125829120,
                            "memory_limit_bytes": None,
                            "raw_mem_usage": "120MiB",
                            "net_io": "n/a",
                            "block_io": "n/a",
                        }
                    ],
                }
            ],
        )

        response = client.get(
            "/api/docker/metrics/history",
            params={
                "service": "summitflow-api",
                "since_minutes": 60,
                "bucket_seconds": 60,
            },
        )

        assert response.status_code == 200
        assert response.json()[0]["samples"][0]["cpu_percent"] == 3.5
        list_series.assert_called_once_with(
            service="summitflow-api",
            manager=None,
            category=None,
            since_minutes=60,
            bucket_seconds=60,
            limit=20000,
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

    def test_live_session_create_uses_internal_browser_target(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        mocker.patch(
            "app.api.docker.live_sessions._create_browser_target",
            new=mocker.AsyncMock(
                return_value={
                    "id": "target-1",
                    "webSocketDebuggerUrl": "ws://browser/devtools/page/target-1",
                }
            ),
        )
        mocker.patch(
            "app.api.docker.live_sessions._configure_viewport",
            new=mocker.AsyncMock(),
        )
        mocker.patch(
            "app.api.docker.live_sessions._refresh_page_metadata",
            new=mocker.AsyncMock(),
        )

        response = client.post(
            "/api/docker/live-sessions",
            json={"target_url": "https://www.amazon.com/photos/all"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "browser"
        assert body["state"] == "active"
        assert body["sensitive"] is True
        assert body["target_url"] == "https://www.amazon.com/photos/all"
        assert body["control_enabled"] is False
        assert body["token_required"] is True
        assert isinstance(body["operator_token"], str)
        assert len(body["operator_token"]) > 20
        assert "webSocketDebuggerUrl" not in body
        assert "ws://" not in response.text

        list_response = client.get("/api/docker/live-sessions")
        assert list_response.status_code == 200
        assert "operator_token" not in list_response.text

    def test_live_session_browser_endpoint_requires_configured_host(self, monkeypatch) -> None:
        from app.api.docker import live_sessions

        monkeypatch.delenv("SUMMITFLOW_LIVE_BROWSER_HOST", raising=False)
        monkeypatch.delenv("SF_BROWSER_HOST", raising=False)
        monkeypatch.delenv("SUMMITFLOW_LIVE_BROWSER_ALLOW_LOCAL", raising=False)
        monkeypatch.delenv("SF_BROWSER_ALLOW_LOCAL", raising=False)

        with pytest.raises(HTTPException) as exc:
            live_sessions._browser_endpoint()

        assert exc.value.status_code == 503
        assert "Browser host is not configured" in exc.value.detail

    def test_sensitive_live_session_frame_requires_operator_token(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            audit_events=[],
        )
        cdp_call = mocker.patch(
            "app.api.docker.live_sessions._cdp_call",
            new=mocker.AsyncMock(return_value={}),
        )

        response = client.get("/api/docker/live-sessions/session-1/frame")

        assert response.status_code == 403
        assert cdp_call.await_count == 0

    def test_live_session_text_control_does_not_echo_input(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            control_enabled=True,
            audit_events=[],
        )
        cdp_call = mocker.patch(
            "app.api.docker.live_sessions._cdp_call",
            new=mocker.AsyncMock(return_value={}),
        )
        mocker.patch(
            "app.api.docker.live_sessions._refresh_page_metadata",
            new=mocker.AsyncMock(),
        )

        response = client.post(
            "/api/docker/live-sessions/session-1/control",
            headers={"X-Live-Session-Token": "operator-token"},
            json={"action": "text", "text": "dont-echo-this"},
        )

        assert response.status_code == 200
        assert "dont-echo-this" not in response.text
        assert cdp_call.await_count == 1
        assert response.json()["last_controlled_at"] is not None

    def test_live_session_control_grant_sets_expiring_lease(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            audit_events=[],
        )

        response = client.post(
            "/api/docker/live-sessions/session-1/control-grant",
            headers={"X-Live-Session-Token": "operator-token"},
            json={"enabled": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["control_enabled"] is True
        assert body["control_owner"] == "operator"
        assert body["control_expires_at"] is not None

    def test_live_session_expired_control_grant_blocks_input(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            control_enabled=True,
            control_expires_at=now - live_sessions.timedelta(seconds=1),
            audit_events=[],
        )

        response = client.post(
            "/api/docker/live-sessions/session-1/control",
            headers={"X-Live-Session-Token": "operator-token"},
            json={"action": "text", "text": "blocked"},
        )

        assert response.status_code == 423
        assert live_sessions._LIVE_SESSIONS["session-1"].control_enabled is False

    def test_live_session_secure_text_uses_non_echoing_plain_text_endpoint(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            control_enabled=True,
            audit_events=[],
        )
        async def fake_cdp_call(*args, **kwargs):
            if args[1] == "Runtime.evaluate":
                return {"result": {"value": True}}
            return {}

        cdp_call = mocker.patch(
            "app.api.docker.live_sessions._cdp_call",
            new=mocker.AsyncMock(side_effect=fake_cdp_call),
        )
        mocker.patch(
            "app.api.docker.live_sessions._refresh_page_metadata",
            new=mocker.AsyncMock(),
        )
        secret_text = "dont-cache-or-echo-this-" * 32

        response = client.post(
            "/api/docker/live-sessions/session-1/secure-text",
            headers={
                "Content-Type": "text/plain;charset=UTF-8",
                "X-Live-Session-Token": "operator-token",
            },
            content=secret_text,
        )

        assert response.status_code == 200
        assert secret_text not in response.text
        assert response.json()["last_controlled_at"] is not None
        assert [call.args[1] for call in cdp_call.await_args_list] == [
            "Runtime.evaluate",
            "Input.insertText",
        ]

    def test_live_session_secure_text_requires_focused_text_field(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            control_enabled=True,
            audit_events=[],
        )

        async def fake_cdp_call(*args, **kwargs):
            if args[1] == "Runtime.evaluate":
                return {"result": {"value": False}}
            return {}

        cdp_call = mocker.patch(
            "app.api.docker.live_sessions._cdp_call",
            new=mocker.AsyncMock(side_effect=fake_cdp_call),
        )
        mocker.patch(
            "app.api.docker.live_sessions._refresh_page_metadata",
            new=mocker.AsyncMock(),
        )
        secret_text = "dont-cache-or-echo-this"

        response = client.post(
            "/api/docker/live-sessions/session-1/secure-text",
            headers={
                "Content-Type": "text/plain;charset=UTF-8",
                "X-Live-Session-Token": "operator-token",
            },
            content=secret_text,
        )

        assert response.status_code == 409
        assert secret_text not in response.text
        assert [call.args[1] for call in cdp_call.await_args_list] == [
            "Runtime.evaluate",
        ]

    def test_live_session_enter_key_dispatches_submit_key_event(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            control_enabled=True,
            audit_events=[],
        )
        cdp_call = mocker.patch(
            "app.api.docker.live_sessions._cdp_call",
            new=mocker.AsyncMock(return_value={}),
        )
        mocker.patch(
            "app.api.docker.live_sessions._refresh_page_metadata",
            new=mocker.AsyncMock(),
        )

        response = client.post(
            "/api/docker/live-sessions/session-1/control",
            headers={"X-Live-Session-Token": "operator-token"},
            json={"action": "key", "key": "Enter"},
        )

        assert response.status_code == 200
        calls = cdp_call.await_args_list
        assert [call.args[1] for call in calls] == [
            "Input.dispatchKeyEvent",
            "Input.dispatchKeyEvent",
        ]
        assert calls[0].args[2] == {
            "type": "keyDown",
            "key": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
            "code": "Enter",
            "text": "\r",
            "unmodifiedText": "\r",
        }
        assert calls[1].args[2] == {
            "type": "keyUp",
            "key": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
            "code": "Enter",
        }

    def test_live_session_text_limit_errors_do_not_echo_input(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            control_enabled=True,
            audit_events=[],
        )
        cdp_call = mocker.patch(
            "app.api.docker.live_sessions._cdp_call",
            new=mocker.AsyncMock(return_value={}),
        )
        mocker.patch(
            "app.api.docker.live_sessions._refresh_page_metadata",
            new=mocker.AsyncMock(),
        )
        secret_text = "s" * (live_sessions._MAX_TEXT_INPUT_CHARS + 1)

        response = client.post(
            "/api/docker/live-sessions/session-1/secure-text",
            headers={
                "Content-Type": "text/plain;charset=UTF-8",
                "X-Live-Session-Token": "operator-token",
            },
            content=secret_text,
        )

        assert response.status_code == 413
        assert secret_text not in response.text
        assert cdp_call.await_count == 0

        json_response = client.post(
            "/api/docker/live-sessions/session-1/control",
            headers={"X-Live-Session-Token": "operator-token"},
            json={"action": "text", "text": secret_text},
        )

        assert json_response.status_code == 413
        assert secret_text not in json_response.text
        assert cdp_call.await_count == 0

    def test_live_session_control_starts_locked(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import live_sessions

        live_sessions._LIVE_SESSIONS.clear()
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        now = live_sessions._now()
        live_sessions._LIVE_SESSIONS["session-1"] = live_sessions._ManagedLiveSession(
            id="session-1",
            kind="browser",
            target_url="https://www.amazon.com/photos/all",
            target_id="target-1",
            ws_url="ws://browser/devtools/page/target-1",
            operator_token_hash=live_sessions._token_hash("operator-token"),
            created_at=now,
            expires_at=now + live_sessions.timedelta(minutes=5),
            viewport_width=1440,
            viewport_height=900,
            audit_events=[],
        )
        cdp_call = mocker.patch(
            "app.api.docker.live_sessions._cdp_call",
            new=mocker.AsyncMock(return_value={}),
        )

        response = client.post(
            "/api/docker/live-sessions/session-1/control",
            headers={"X-Live-Session-Token": "operator-token"},
            json={"action": "key", "key": "Enter"},
        )

        assert response.status_code == 423
        assert cdp_call.await_count == 0
