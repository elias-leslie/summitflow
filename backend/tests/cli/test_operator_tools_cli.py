"""Tests for canonical st operator commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import service, setup, vm
from cli.lib.service_ops import ProjectServices
from cli.main import app as main_app

runner = CliRunner()


def _project() -> ProjectServices:
    return ProjectServices(
        project_id="summitflow",
        root=Path("/repo"),
        backend_service="summitflow-backend.service",
        frontend_service="summitflow-frontend.service",
        default_workers=("summitflow-worker.service",),
        optional_workers=(),
        backend_port=8001,
        frontend_port=3001,
        backend_dir=Path("/repo/backend"),
        frontend_dir=Path("/repo/frontend"),
        health_endpoint="/health",
    )


def test_service_status_reads_native_service_state() -> None:
    with (
        patch("cli.commands.service.service_ops.project_ids", return_value=["summitflow"]),
        patch("cli.commands.service._load", return_value=_project()),
        patch("cli.commands.service.service_ops.service_state", return_value="active") as state,
    ):
        result = runner.invoke(service.app, ["status"])

    assert result.exit_code == 0
    assert "summitflow-backend.service:active" in result.output
    assert state.call_count == 3


def test_service_rebuild_uses_native_steps() -> None:
    with (
        patch("cli.commands.service._load", return_value=_project()),
        patch("cli.commands.service.service_ops.ensure_infra", return_value=0),
        patch("cli.commands.service.service_ops.build_frontend", return_value=0),
        patch("cli.commands.service.service_ops.run_migrations", return_value=0),
        patch("cli.commands.service.service_ops.sync_systemd_units"),
        patch("cli.commands.service.service_ops.restart_service", return_value=0) as restart,
        patch("cli.commands.service.service_ops.verify_health", return_value=0),
        patch("cli.commands.service.service_ops.sync_seeds"),
    ):
        result = runner.invoke(service.app, ["rebuild", "summitflow"])

    assert result.exit_code == 0
    assert restart.call_count == 3


def test_service_stop_uses_confirm_gate() -> None:
    with (
        patch("cli.commands.service._load", return_value=_project()),
        patch("cli.commands.service.confirm_gate") as confirm_gate,
        patch("cli.commands.service.service_ops.stop_services", return_value=0) as stop_services,
    ):
        result = runner.invoke(service.app, ["stop", "summitflow", "--confirm", "abc12345"])

    assert result.exit_code == 0
    confirm_gate.assert_called_once()
    stop_services.assert_called_once()


def test_check_runs_native_tool() -> None:
    with (
        patch("cli.commands.check._tool_configs", return_value={"ruff": {"label": "LINT", "binary": "ruff"}}),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "ruff"])

    assert result.exit_code == 0
    run_tool.assert_called_once()


def test_db_runs_native_migration_status() -> None:
    with (
        patch("cli.commands.db._detect_project", return_value="summitflow"),
        patch("cli.commands.db._alembic", return_value=0) as alembic,
    ):
        result = runner.invoke(main_app, ["db", "migrate", "status"])

    assert result.exit_code == 0
    alembic.assert_called_once_with("summitflow", ["current", "-v"])


def test_browser_health_uses_native_health() -> None:
    with patch("cli.commands.browser._print_health") as health:
        result = runner.invoke(main_app, ["browser", "health"])

    assert result.exit_code == 0
    health.assert_called_once()


def test_web_runs_agent_hub_service_code() -> None:
    with patch("cli.commands.web._run_agent_hub_web", return_value=0) as run_web:
        result = runner.invoke(main_app, ["web", "search", "--query", "SummitFlow", "--limit", "1"])

    assert result.exit_code == 0
    assert run_web.call_args.args[0]["command"] == "search"
    assert run_web.call_args.args[0]["query"] == "SummitFlow"


class _FakeVmClient:
    def __init__(self) -> None:
        self.stopped: list[str] = []
        self.destroyed: list[str] = []

    def status(self, vmid: str) -> dict[str, object]:
        return {
            "vmid": vmid,
            "name": "test-vm",
            "status": "running",
            "cpu": 0.12,
            "mem": 1024 * 1024,
            "maxmem": 2 * 1024 * 1024,
            "uptime": 7,
        }

    def stop(self, vmid: str) -> None:
        self.stopped.append(vmid)

    def destroy(self, vmid: str) -> None:
        self.destroyed.append(vmid)


def test_vm_status_uses_native_client() -> None:
    with patch("cli.commands.vm._client", return_value=_FakeVmClient()):
        result = runner.invoke(main_app, ["vm", "status", "100"])

    assert result.exit_code == 0
    assert "VM 100 (test-vm): running" in result.output


def test_vm_stop_uses_confirm_gate() -> None:
    fake = _FakeVmClient()
    with (
        patch("cli.commands.vm._client", return_value=fake),
        patch("cli.commands.vm.confirm_gate") as confirm_gate,
    ):
        result = runner.invoke(vm.app, ["stop", "100", "--confirm", "abc12345"])

    assert result.exit_code == 0
    confirm_gate.assert_called_once()
    assert fake.stopped == ["100"]


def test_vm_destroy_confirms_then_calls_native_destroy() -> None:
    fake = _FakeVmClient()
    with (
        patch("cli.commands.vm._client", return_value=fake),
        patch("cli.commands.vm.confirm_gate") as confirm_gate,
    ):
        result = runner.invoke(vm.app, ["destroy", "101", "--confirm", "abc12345"])

    assert result.exit_code == 0
    confirm_gate.assert_called_once()
    assert fake.destroyed == ["101"]


def test_setup_services_dry_run_does_not_mutate() -> None:
    with patch("cli.commands.setup._link_st") as link_st:
        result = runner.invoke(setup.app, ["services", "--dry-run"])

    assert result.exit_code == 0
    assert "SETUP SERVICES" in result.output
    link_st.assert_not_called()
