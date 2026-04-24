"""Tests for canonical st operator command wrappers."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import service, setup, vm
from cli.main import app as main_app

runner = CliRunner()


def test_service_status_forwards_to_rebuild_status() -> None:
    with patch("cli.commands.service.run_forwarded") as forwarded:
        result = runner.invoke(service.app, ["status", "summitflow"])

    assert result.exit_code == 0
    forwarded.assert_called_once_with("rebuild.sh", ["--status", "summitflow"])


def test_service_rebuild_forwards_flags_in_script_order() -> None:
    with patch("cli.commands.service.run_forwarded") as forwarded:
        result = runner.invoke(service.app, ["rebuild", "--detach", "--include-all-workers", "agent-hub"])

    assert result.exit_code == 0
    forwarded.assert_called_once_with("rebuild.sh", ["--detach", "--include-all-workers", "agent-hub"])


def test_service_stop_uses_confirm_gate() -> None:
    with (
        patch("cli.commands.service.confirm_gate") as confirm_gate,
        patch("cli.commands.service.run_forwarded") as forwarded,
    ):
        result = runner.invoke(service.app, ["stop", "--confirm", "abc12345"])

    assert result.exit_code == 0
    confirm_gate.assert_called_once()
    forwarded.assert_called_once_with("shutdown.sh", [])


def test_check_forwards_unknown_args_to_dt() -> None:
    with patch("cli.commands.check.run_forwarded") as forwarded:
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    forwarded.assert_called_once_with("dt", ["--quick", "--changed-only"])


def test_db_forwards_unknown_args_to_db_runner() -> None:
    with patch("cli.commands.db.run_forwarded") as forwarded:
        result = runner.invoke(main_app, ["db", "migrate", "status"])

    assert result.exit_code == 0
    forwarded.assert_called_once_with("db", ["migrate", "status"])


def test_browser_forwards_to_sf_browser() -> None:
    with patch("cli.commands.browser.run_forwarded") as forwarded:
        result = runner.invoke(main_app, ["browser", "health"])

    assert result.exit_code == 0
    forwarded.assert_called_once_with("sf-browser", ["health"])


def test_web_forwards_to_web_research() -> None:
    with patch("cli.commands.web.run_forwarded") as forwarded:
        result = runner.invoke(main_app, ["web", "search", "--query", "SummitFlow", "--limit", "1"])

    assert result.exit_code == 0
    forwarded.assert_called_once_with("web-research", ["search", "--query", "SummitFlow", "--limit", "1"])


def test_vm_forwards_to_proxmox_vm() -> None:
    with patch("cli.commands.vm.run_forwarded") as forwarded:
        result = runner.invoke(main_app, ["vm", "status", "100"])

    assert result.exit_code == 0
    forwarded.assert_called_once_with("proxmox-vm.sh", ["status", "100"])


def test_vm_stop_uses_confirm_gate() -> None:
    with (
        patch("cli.commands.vm.confirm_gate") as confirm_gate,
        patch("cli.commands.vm.run_forwarded") as forwarded,
    ):
        result = runner.invoke(vm.app, ["stop", "100", "--confirm", "abc12345"])

    assert result.exit_code == 0
    confirm_gate.assert_called_once()
    forwarded.assert_called_once_with("proxmox-vm.sh", ["stop", "100"])


def test_vm_destroy_confirms_then_answers_underlying_prompt() -> None:
    with (
        patch("cli.commands.vm.confirm_gate") as confirm_gate,
        patch("cli.commands.vm.run_forwarded_with_input") as forwarded,
    ):
        result = runner.invoke(vm.app, ["destroy", "101", "--confirm", "abc12345"])

    assert result.exit_code == 0
    confirm_gate.assert_called_once()
    forwarded.assert_called_once_with("proxmox-vm.sh", ["destroy", "101"], "y\n")


def test_setup_services_dry_run_does_not_forward() -> None:
    with patch("cli.commands.setup.run_forwarded") as forwarded:
        result = runner.invoke(setup.app, ["services", "--dry-run"])

    assert result.exit_code == 0
    assert "SETUP SERVICES" in result.output
    forwarded.assert_not_called()


def test_forwarded_missing_command_exits_127() -> None:
    with (
        patch("cli.commands.operator_forward.resolve_command", return_value="/missing"),
        patch("cli.commands.operator_forward.subprocess.run") as run,
    ):
        run.return_value.returncode = 127
        result = runner.invoke(main_app, ["check", "foo"])

    assert result.exit_code == 127
    run.assert_called_once_with(["/missing", "foo"], check=False)
