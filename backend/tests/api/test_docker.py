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

_RUNTIME_IDENTITIES = [
    {"project": {"id": "agent-hub"},
     "runtime": {"backend_port": 8003, "frontend_port": 3003, "health_endpoint": "/health"},
     "services": {"backend": "agent-hub-backend.service", "frontend": "agent-hub-frontend.service",
                  "default_workers": ["agent-hub-hatchet-ops-worker.service"],
                  "optional_workers": ["agent-hub-hatchet-agent-worker.service"]}},
    {"project": {"id": "vantage"},
     "runtime": {"backend_port": 8004, "frontend_port": 3004, "health_endpoint": "/health"},
     "services": {"backend": "vantage-backend.service", "frontend": "vantage-frontend.service",
                  "default_workers": ["vantage-hatchet-worker.service"]}},
]

client = TestClient(app)


@pytest.fixture(autouse=True)
def stack_unit_installed(mocker: MockerFixture) -> None:
    mocker.patch("app.utils.nightshift_stack.stack_installed", return_value=True)
    mocker.patch("app.access_control.settings.summitflow_loopback_is_owner", True)


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

    def test_missing_local_unit_does_not_claim_remote_service_stopped(self) -> None:
        from app.api.docker._status_probing import _classify_systemd_state

        state, health, status = _classify_systemd_state("inactive", "dead", "not-found", False, None, "app")
        assert state == "unknown"
        assert health == ""
        assert "not installed locally" in status

    @pytest.mark.parametrize("active,load,expected", [
        ("inactive", "loaded", "stopped"), ("failed", "loaded", "stopped"),
        ("inactive", "not-found", "unknown"),
    ])
    def test_forwarded_http_cannot_prove_local_unit_is_running(self, active, load, expected):
        from app.api.docker._status_probing import _classify_systemd_state

        state, health, _ = _classify_systemd_state(active, "dead", load, True, 200, "app")
        assert state == expected
        assert health != "healthy"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("container_state,rc,expected", [("exited|", 0, "stopped"), ("", 1, "unknown"),
                                                           ("running|healthy", 0, "running")])
    async def test_forwarded_ports_cannot_prove_a_docker_container_is_running(self, mocker, container_state, rc, expected):
        from app.api.docker import _status_probing, helpers

        mocker.patch.object(_status_probing, "_port_open", new=mocker.AsyncMock(return_value=True))
        inspect = mocker.patch.object(helpers, "_run_command", new=mocker.AsyncMock(return_value=(container_state, "", rc)))
        svc = {"service": "db", "display_name": "db", "container_service": "db", "category": "infra", "ports": ["8123"]}
        row = await _status_probing._infra_status(svc)
        assert row.state == expected
        assert (row.health == "healthy") == (expected == "running")
        assert "inspect" in inspect.call_args.args

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rows,expected", [
        ({"api.service": {"ActiveState": "inactive", "SubState": "guest-stopped", "Error": "Guest is stopped"}}, "stopped"),
        ({"api.service": {"Error": "Could not reach guest"}}, "unknown"),
        ({"api.service": {"LoadState": "not-found", "ActiveState": "inactive"}}, "unknown"),
    ])
    async def test_unavailable_guest_is_truthful_even_when_bridge_answers(self, mocker, rows, expected):
        from app.api.docker import _status_probing, helpers

        svc = {"service": "moved-api", "display_name": "moved-api", "manager": "systemd", "category": "app",
               "unit": "api.service", "ports": ["8123"], "deployment": {
                   "kind": "proxmox", "ssh_host": "pve-example", "vmid": 456, "manager": "system"}}
        mocker.patch("app.runtime_deployment.unit_states", return_value=rows)
        mocker.patch.object(helpers, "_probe_http", new=mocker.AsyncMock(return_value=(True, 200)))
        row = await _status_probing._systemd_status(svc)
        assert row.state == expected
        assert row.health != "healthy"
        assert not row.controllable
        assert not row.log_streaming
        assert row.auto_start is None
        assert "not installed locally" not in row.status

    @pytest.mark.asyncio
    async def test_remote_api_stop_includes_paired_timer_and_socket_services(self, mocker):
        from app.api.docker import _runtime_control

        target = {"kind": "proxmox", "ssh_host": "pve-example", "vmid": 456, "user": "appuser", "uid": 1234}
        api = {"service": "moved-api", "manager": "systemd", "project_id": "moved", "unit": "api.service", "deployment": target}
        definitions = [api, *[{**api, "service": unit, "unit": unit} for unit in ["jobs.timer", "queue.socket"]]]
        mocker.patch.object(_runtime_control, "runtime_service_definitions", return_value=definitions)
        remote = mocker.patch("app.runtime_deployment.control_units")
        assert (await _runtime_control._systemd_service_action(api, "stop")).success
        assert remote.call_args.args[1] == "stop"
        assert set(remote.call_args.args[2]) == {"api.service", "jobs.timer", "jobs.service", "queue.socket", "queue.service"}

    @pytest.mark.asyncio
    async def test_guest_logs_and_streaming_use_remote_capabilities(self, mocker):
        from app.api.docker import routes

        svc = {"manager": "systemd", "unit": "api.service", "deployment": {
            "kind": "proxmox", "ssh_host": "pve-example", "vmid": 456, "user": "appuser", "uid": 1234}}
        mocker.patch.object(routes, "_service_definition", return_value=svc)
        recent = mocker.patch("app.runtime_deployment.recent_logs", return_value="test log")
        local = mocker.patch.object(routes, "_run_journalctl_user", new=mocker.AsyncMock())
        assert await routes.get_logs("moved-api", tail=7, follow=False) == {"logs": "test log"}
        assert recent.call_args.args[1:] == ("api.service", 7)
        local.assert_not_called()
        with pytest.raises(HTTPException, match="Live streaming"):
            await routes.get_logs("moved-api", tail=7, follow=True)

    @pytest.mark.asyncio
    async def test_guest_metrics_never_inspect_workstation_pids(self, mocker):
        from app.api.docker import _metrics_collection

        mocker.patch.object(_metrics_collection, "runtime_service_definitions", return_value=[
            {"manager": "systemd", "deployment": {"kind": "proxmox"}, "unit": "api.service"},
        ])
        local = mocker.patch.object(_metrics_collection, "_systemd_service_metric", new=mocker.AsyncMock())
        assert await _metrics_collection._runtime_metrics() == []
        local.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_units_use_catalog_target_and_never_local_systemctl(self, mocker):
        from app import project_identity
        from app.api.docker import _status_probing, helpers

        identity = {"project": {"id": "moved"}, "runtime": {
            "backend_port": 8123,
            "deployment": {"kind": "proxmox", "ssh_host": "pve-example", "vmid": 456,
                           "user": "appuser", "uid": 1234},
        }, "services": {"backend": "moved.service", "default_workers": ["jobs.service"]}}
        mocker.patch.object(project_identity, "list_project_identities", return_value=[identity])
        mocker.patch.object(project_identity, "get_project_lifecycles", return_value={"moved": "active"})
        local = mocker.patch.object(helpers, "_systemd_unit_state", new=mocker.AsyncMock())
        remote = mocker.patch("app.runtime_deployment.unit_states", return_value={
            "moved.service": {"ActiveState": "active", "SubState": "running", "LoadState": "loaded", "UnitFileState": "enabled"},
            "jobs.service": {"ActiveState": "failed", "SubState": "failed", "LoadState": "loaded"},
        })
        mocker.patch.object(helpers, "_probe_http", new=mocker.AsyncMock(return_value=(True, 200)))
        mocker.patch.object(_status_probing, "_infra_status", new=mocker.AsyncMock(return_value=None))
        rows = [r for r in await _status_probing._runtime_service_statuses() if r is not None]
        local.assert_not_called()
        remote.assert_called_once()
        target, units = remote.call_args.args
        assert (target.ssh_host, target.vmid, target.user, target.uid) == ("pve-example", 456, "appuser", 1234)
        assert set(units) == {"moved.service", "jobs.service"}
        assert rows[0].state == "running"
        assert "VM 456" in rows[0].status
        assert rows[1].state == "stopped"

    @pytest.mark.asyncio
    async def test_remote_action_never_clears_workstation_ports(self, mocker):
        from app.api.docker import _runtime_control, helpers

        target = {"kind": "proxmox", "ssh_host": "pve-example", "vmid": 456, "user": "appuser", "uid": 1234}
        svc = {"service": "moved-api", "manager": "systemd", "unit": "moved.service",
               "ports": ["8123"], "deployment": target}
        mocker.patch.object(helpers, "_service_definition", return_value=svc)
        local = mocker.patch.object(helpers, "_run_systemctl_user", new=mocker.AsyncMock())
        clear = mocker.patch.object(helpers, "_clear_service_ports", new=mocker.AsyncMock())
        remote = mocker.patch("app.runtime_deployment.control_units")
        result = await _runtime_control._service_action("moved-api", "restart")
        assert result.success
        assert remote.call_args.args[1:] == ("restart", ["moved.service"])
        local.assert_not_called()
        clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_runtime_discovers_new_project_without_restart(self, mocker: MockerFixture) -> None:
        from app.api.docker import _status_probing, helpers

        identities = []
        retired: set[str] = set()
        mocker.patch("app.project_identity.list_project_identities", side_effect=lambda: identities)
        mocker.patch(
            "app.project_identity.get_project_lifecycles",
            side_effect=lambda project_ids, **_: {
                project_id: "retired" if project_id in retired else "active"
                for project_id in project_ids
            },
        )
        probe = mocker.patch.object(_status_probing, "_runtime_service_status", new=mocker.AsyncMock())
        await helpers._runtime_service_statuses()
        assert not any(call.args[0]["service"] == "new-project-api" for call in probe.call_args_list)

        identities.append({
            "project": {"id": "new-project"},
            "runtime": {"backend_port": 8123, "health_endpoint": "/healthz"},
            "services": {
                "backend": "new-project.service", "frontend": "new-project.service",
                "default_workers": ["new-project-jobs.service"],
                "optional_workers": ["new-project-extra.service"],
            },
        })
        probe.reset_mock()
        await helpers._runtime_service_statuses()
        discovered = [call.args[0] for call in probe.call_args_list if call.args[0].get("project_id") == "new-project"]
        assert {item["unit"] for item in discovered} == {
            "new-project.service", "new-project-jobs.service", "new-project-extra.service",
        }
        assert len(discovered) == 3
        definition = helpers._service_definition("new-project-api")
        assert definition["probe_url"] == "http://localhost:8123/healthz"
        assert definition["ports"] == ["8123"]
        identities[0]["project"]["lifecycle"] = "retired"
        assert helpers._service_definition("new-project-api")["ports"] == ["8123"]
        retired.add("new-project")
        with pytest.raises(HTTPException, match="Unknown service"):
            helpers._service_definition("new-project-api")

    @pytest.mark.asyncio
    async def test_backup_fallback_confines_note_to_safe_filename(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        from app.api.docker import routes

        mocker.patch.object(routes, "BACKUP_DIR", tmp_path)
        mocker.patch.object(
            routes,
            "_run_command",
            new=mocker.AsyncMock(return_value=("database dump", "", 0)),
        )

        result = await routes._backup_fallback(
            "../../escape; touch owned",
            RuntimeError("workflow unavailable"),
        )

        assert result.success is True
        created = list(tmp_path.glob("*.sql"))
        assert len(created) == 1
        assert created[0].parent == tmp_path
        assert created[0].name.endswith("-escape--touch-owned.sql")

    @pytest.mark.asyncio
    async def test_container_action_uses_docker_until_the_stack_unit_is_installed(
        self, mocker: MockerFixture
    ) -> None:
        from app.api.docker import _runtime_control

        mocker.patch("app.utils.nightshift_stack.stack_installed", return_value=False)
        mocker.patch.object(
            _runtime_control._h, "_service_definition",
            return_value={"manager": "docker", "container_service": "redis"},
        )
        run_docker = mocker.patch.object(
            _runtime_control._h, "_run_docker", new=mocker.AsyncMock(return_value=("", "", 0))
        )
        request = mocker.patch("app.utils.nightshift_stack.request_stack")

        result = await _runtime_control._service_action("redis", "restart")

        assert result.success is True
        assert run_docker.await_args_list[0].args[:2] == ("docker", "restart")
        request.assert_not_called()

    @pytest.mark.asyncio
    async def test_container_action_goes_through_nightshift_and_can_be_pending(
        self, mocker: MockerFixture
    ) -> None:
        from app.api.docker import _runtime_control
        from app.utils.nightshift_stack import StackResult

        mocker.patch.object(
            _runtime_control._h, "_service_definition",
            return_value={"manager": "docker", "container_service": "redis"},
        )
        mocker.patch(
            "app.utils.nightshift_stack.request_stack",
            return_value=StackResult(True, "waiting", pending=True, approve_url="https://example.test/n/1"),
        )

        result = await _runtime_control._service_action("redis", "restart")

        assert result.pending is True
        assert result.approve_url == "https://example.test/n/1"
        assert "whole stack" in result.message

    def test_runtime_services_come_from_identity_plus_infra(self, mocker: MockerFixture) -> None:
        from app import project_identity
        from app.api.docker.constants import runtime_service_definitions

        mocker.patch.object(project_identity, "list_project_identities", return_value=_RUNTIME_IDENTITIES)
        mocker.patch.object(project_identity, "get_project_lifecycles",
                            side_effect=lambda ids, **_: dict.fromkeys(ids, "active"))
        services = {svc["service"]: svc for svc in runtime_service_definitions()}

        assert set(services) == {
            "postgres", "redis", "hatchet",
            "agent-hub-api", "agent-hub-web", "agent-hub-hatchet-ops-worker", "agent-hub-hatchet-agent-worker",
            "vantage-api", "vantage-web", "vantage-hatchet-worker",
        }
        assert services["agent-hub-api"]["ports"] == ["8003"]
        assert services["agent-hub-api"]["probe_url"] == "http://localhost:8003/health"
        assert services["agent-hub-hatchet-agent-worker"]["unit"] == "agent-hub-hatchet-agent-worker.service"
        assert services["vantage-hatchet-worker"]["project_id"] == "vantage"

    def test_detect_repo_root_walks_up_container_layout(self, tmp_path) -> None:
        from app.api import docker as docker_api

        repo_root = tmp_path / "repo"
        (repo_root / "backend" / "cli").mkdir(parents=True)
        (repo_root / "backend" / "app").mkdir(parents=True)

        module_path = repo_root / "app" / "api" / "docker.py"
        module_path.parent.mkdir(parents=True)
        module_path.write_text("# test\n")

        assert docker_api._detect_repo_root(module_path) == repo_root

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

        response = client.post("/api/docker/runtime", json={"mode": "prod"})

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Saved Docker parity preference: prod. Live services remain native apps with Docker infra.",
            "pending": False,
            "approve_url": None,
        }
        write_mode.assert_called_once_with("prod")

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

        from app import project_identity

        mocker.patch.object(project_identity, "list_project_identities", return_value=_RUNTIME_IDENTITIES)
        mocker.patch.object(project_identity, "get_project_lifecycles",
                            side_effect=lambda ids, **_: dict.fromkeys(ids, "active"))
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
            "vantage-hatchet-worker",
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

    def test_runtime_service_status_keeps_unit_unknown_when_only_http_is_available(
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
                {"service": "summitflow-api", "display_name": "summitflow-api", "manager": "systemd",
                 "category": "app", "unit": "summitflow-backend.service", "ports": ["8001"],
                 "probe_url": "http://localhost:8001/health", "project_id": "summitflow"},
            )
        )

        assert result == docker_api.RuntimeServiceStatus(
            name="summitflow-backend.service",
            service="summitflow-api",
            display_name="summitflow-api",
            manager="systemd",
            category="app",
            state="unknown",
            health="",
            status="systemd timed-out",
            ports=["8001"],
        )

    def test_host_monitor_status_reads_system_unit_and_is_not_controllable(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import _status_probing

        user = mocker.patch(
            "app.api.docker.helpers._run_systemctl_user",
            new=mocker.AsyncMock(return_value=("ActiveState=inactive\nUnitFileState=disabled\n", "", 0)),
        )
        system = mocker.patch(
            "app.api.docker._process_execution._run_systemctl_system",
            new=mocker.AsyncMock(
                return_value=("LoadState=loaded\nActiveState=active\nSubState=running\nUnitFileState=enabled\n", "", 0)
            ),
        )
        mocker.patch("app.api.docker.helpers._probe_http", new=mocker.AsyncMock(return_value=(False, None)))
        svc = {
            "unit": "summitflow-host-monitor.service",
            "service": "summitflow-host-monitor",
            "display_name": "summitflow-host-monitor",
            "category": "worker",
            "ports": [],
        }

        result = asyncio.run(_status_probing._systemd_status(svc))

        user.assert_not_awaited()
        assert system.await_args.args[:2] == ("show", "summitflow-host-monitor.service")
        assert result.state == "running"
        assert result.controllable is False
        assert result.auto_start is None

    def test_host_monitor_actions_never_touch_the_user_unit(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import _runtime_control

        user = mocker.patch("app.api.docker.helpers._run_systemctl_user", new=mocker.AsyncMock())
        svc = {"unit": "summitflow-host-monitor.service", "service": "summitflow-host-monitor"}
        mocker.patch("app.api.docker.helpers._service_definition", return_value={**svc, "manager": "systemd"})

        stop = asyncio.run(_runtime_control._systemd_service_action(svc, "stop"))
        autostart = asyncio.run(_runtime_control._set_service_autostart("summitflow-host-monitor", False))

        assert stop.success is False and "system unit" in stop.message
        assert autostart.success is False
        user.assert_not_awaited()

    def test_get_metrics_does_not_persist_samples(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import docker as docker_api

        mocker.patch(
            "app.api.docker.routes._runtime_metrics",
            new=mocker.AsyncMock(return_value=[
                docker_api.RuntimeServiceMetrics(
                    name="summitflow-backend.service", service="summitflow-api", cpu_percent="1.00%",
                    mem_usage="1.0MiB", mem_percent="0.10%", net_io="n/a", block_io="n/a",
                )
            ]),
        )
        record = mocker.patch("app.api.docker.routes.runtime_metric_store.record_runtime_metric_samples")

        response = client.get("/api/docker/metrics")

        assert response.status_code == 200
        assert response.json()[0]["cpu_percent"] == "1.00%"
        record.assert_not_called()

    def test_metrics_history_window_clamps_to_one_day(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SUMMITFLOW_RUNTIME_METRICS_RETENTION_DAYS", "14")
        list_series = mocker.patch(
            "app.api.docker.routes.runtime_metric_store.list_runtime_metric_series", return_value=[],
        )

        assert client.get("/api/docker/metrics/history", params={"since_minutes": 43200}).status_code == 200

        assert list_series.call_args.kwargs["since_minutes"] == 24 * 60

    def test_metrics_summary_endpoint_is_retired(self) -> None:
        # The CLI reads summaries from storage directly; no HTTP caller remains.
        assert client.get("/api/docker/metrics/summary").status_code == 404

    def test_systemd_metric_uses_cgroup_cpu_delta_and_memory_current(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api.docker import _metrics_collection

        _metrics_collection._cpu_samples.clear()
        readings = iter([
            ("ActiveState=active\nCPUUsageNSec=1000000000\nMemoryCurrent=104857600\n", "", 0),
            ("ActiveState=active\nCPUUsageNSec=1250000000\nMemoryCurrent=104857600\n", "", 0),
        ])
        mocker.patch(
            "app.api.docker.helpers._run_systemctl_user",
            new=mocker.AsyncMock(side_effect=lambda *args, **kwargs: next(readings)),
        )
        clock = iter([10_000_000_000, 10_500_000_000])
        mocker.patch.object(_metrics_collection, "_monotonic_ns", side_effect=lambda: next(clock))
        mocker.patch.object(_metrics_collection, "_FIRST_SAMPLE_DELAY_SECONDS", 0)
        mocker.patch.object(_metrics_collection, "_total_memory_bytes", return_value=1024 * 1024 * 1024)

        metric = asyncio.run(_metrics_collection._systemd_service_metric(
            {"unit": "summitflow-backend.service", "service": "summitflow-api"}
        ))

        # 0.25s of CPU over 0.5s wall time = 50% of one core, whole cgroup
        assert metric is not None
        assert metric.cpu_percent == "50.00%"
        assert metric.mem_usage == "100.0MiB"
        assert metric.mem_percent == "9.77%"
        _metrics_collection._cpu_samples.clear()

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
                "api_url": "https://192.0.2.33:8006",
                "token_id": "root@pam!automation",
                "token_secret": "secret",
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
                {
                    "onboot": 1,
                },
            ],
        )

        response = client.get("/api/docker/proxmox")

        assert response.status_code == 200
        assert response.json() == {
            "configured": True,
            "reachable": True,
            "api_url": "https://192.0.2.33:8006",
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
                    "onboot": True,
                }
            ],
        }

    def test_proxmox_set_autostart_success(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import _runtime_proxmox

        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        mocker.patch.object(
            _runtime_proxmox,
            "_proxmox_config",
            return_value={
                "api_url": "https://192.0.2.33:8006",
                "token_id": "root@pam!automation",
                "token_secret": "secret",
            },
        )
        put_mock = mocker.patch.object(
            _runtime_proxmox,
            "_sync_proxmox_put_json",
            return_value=None,
        )

        response = client.post(
            "/api/docker/proxmox/guests/davion-gem/qemu/100/autostart",
            json={"enabled": True},
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "node": "davion-gem",
            "guest_type": "qemu",
            "vmid": 100,
            "onboot": True,
            "task": None,
        }
        put_mock.assert_called_once_with(
            "https://192.0.2.33:8006",
            "root@pam!automation",
            "secret",
            "/nodes/davion-gem/qemu/100/config",
            {"onboot": 1},
        )

    def test_proxmox_control_guest_success(
        self,
        mocker: MockerFixture,
    ) -> None:
        from app.api import _runtime_proxmox

        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        mocker.patch.object(
            _runtime_proxmox,
            "_proxmox_config",
            return_value={
                "api_url": "https://192.0.2.33:8006",
                "token_id": "root@pam!automation",
                "token_secret": "secret",
            },
        )
        post_mock = mocker.patch.object(
            _runtime_proxmox,
            "_sync_proxmox_post_json",
            return_value="UPID:davion-gem:00001234:5678",
        )

        response = client.post("/api/docker/proxmox/guests/davion-gem/qemu/100/start")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "node": "davion-gem",
            "guest_type": "qemu",
            "vmid": 100,
            "action": "start",
            "task": "UPID:davion-gem:00001234:5678",
        }
        post_mock.assert_called_once_with(
            "https://192.0.2.33:8006",
            "root@pam!automation",
            "secret",
            "/nodes/davion-gem/qemu/100/status/start",
        )

    def test_proxmox_control_guest_invalid_action(
        self,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch("app.api.docker.helpers._INTERNAL_SECRET", "")
        response = client.post("/api/docker/proxmox/guests/davion-gem/qemu/100/invalid")
        assert response.status_code == 422
