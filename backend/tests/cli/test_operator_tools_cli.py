"""Tests for canonical st operator commands."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from cli.commands import browser, check, docker, service, setup, vm
from cli.lib import service_ops
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


def test_service_run_large_output_goes_to_details_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = "\n".join(f"line {index}" for index in range(45))
    result = subprocess.CompletedProcess(["pnpm", "build"], 0, stdout=output, stderr="")
    with patch("cli.lib.service_ops.subprocess.run", return_value=result):
        exit_code = service_ops.run(["pnpm", "build"], cwd=tmp_path)

    captured = capsys.readouterr()
    details = tmp_path / ".dev-tools" / "service-pnpm-build-details.txt"
    assert exit_code == 0
    assert details.read_text(encoding="utf-8") == output
    assert "line 0" not in captured.out
    assert "SERVICE:OK:0|lines=45|details:.dev-tools/service-pnpm-build-details.txt" in captured.out


def test_service_run_quiet_success_suppresses_success_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = subprocess.CompletedProcess(["alembic", "upgrade", "head"], 0, stdout="INFO ok\n", stderr="")
    with patch("cli.lib.service_ops.subprocess.run", return_value=result):
        exit_code = service_ops.run(["alembic", "upgrade", "head"], cwd=tmp_path, quiet_success=True)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_service_run_quiet_success_keeps_failure_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = subprocess.CompletedProcess(["alembic", "upgrade", "head"], 1, stdout="", stderr="failed\n")
    with patch("cli.lib.service_ops.subprocess.run", return_value=result):
        exit_code = service_ops.run(["alembic", "upgrade", "head"], cwd=tmp_path, quiet_success=True)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "failed" in captured.err


def test_build_frontend_suppresses_successful_build_output() -> None:
    project = _project()

    with (
        patch.object(Path, "exists", return_value=True),
        patch("cli.lib.service_ops.shutil.rmtree"),
        patch("cli.lib.service_ops.run", return_value=0) as run,
    ):
        assert service_ops.build_frontend(project) == 0

    run.assert_called_once_with(["pnpm", "build"], cwd=project.frontend_dir, quiet_success=True)


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


def test_check_changed_only_skips_unrelated_tools() -> None:
    configs = {
        "pytest": {"label": "TEST", "binary": "pytest", "pass_path": False},
        "tsc": {"label": "TSC", "binary": "npx", "args": "tsc --noEmit", "pass_path": False},
    }
    with (
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._changed_files", return_value=["config.toml"]),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    assert "TEST:SKIP:pytest:no_relevant_changed_paths" in result.output
    assert "TSC:SKIP:tsc:no_relevant_changed_paths" in result.output
    run_tool.assert_not_called()


def test_check_normalizes_repo_relative_explicit_paths(tmp_path: Path) -> None:
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app.ts").write_text("", encoding="utf-8")
    configs = {
        "biome": {
            "label": "BIOME",
            "binary": "biome",
            "working_dir": "frontend",
        }
    }

    with (
        patch("cli.commands.check._repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "biome", "--", "frontend/src/app.ts"])

    assert result.exit_code == 0
    run_tool.assert_called_once_with("biome", configs["biome"], ["src/app.ts"])


def test_check_normalizes_repo_root_explicit_paths_outside_tool_cwd(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    configs = {
        "biome": {
            "label": "BIOME",
            "binary": "biome",
            "working_dir": "frontend",
        }
    }

    with (
        patch("cli.commands.check._repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "biome", "--", "README.md"])

    assert result.exit_code == 0
    run_tool.assert_called_once_with("biome", configs["biome"], [str(tmp_path / "README.md")])


def test_check_resolves_npx_tool_to_local_binary(tmp_path: Path) -> None:
    local_bin = tmp_path / "frontend" / "node_modules" / ".bin"
    local_bin.mkdir(parents=True)
    tsc = local_bin / "tsc"
    tsc.write_text("#!/bin/sh\n", encoding="utf-8")

    command = check._resolve_command("npx", tmp_path, tmp_path / "frontend", ["tsc", "--noEmit"])

    assert command == [str(tsc), "--noEmit"]


def test_check_tool_output_goes_to_details_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=0,
        stdout="line 1\n2187 passed in 19.87s\n",
        stderr="",
    )
    with (
        patch("cli.commands.check._repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", return_value=result),
    ):
        exit_code = check._run_tool("pytest", {"label": "TEST", "binary": "pytest"}, [])

    captured = capsys.readouterr()
    details = tmp_path / ".dev-tools" / "pytest-details.txt"
    assert exit_code == 0
    assert details.read_text(encoding="utf-8") == "line 1\n2187 passed in 19.87s\n"
    assert "line 1" not in captured.out
    assert "TEST:OK:0|details:.dev-tools/pytest-details.txt|hint:2187 passed in 19.87s" in captured.out


def test_check_tool_hint_prefers_result_summary_over_late_runtime_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=0,
        stdout=(
            "===================== 2198 passed, 97 deselected in 41.52s =====================\n"
            "RuntimeWarning: Enable tracemalloc to get the object allocation traceback\n"
        ),
        stderr="",
    )
    with (
        patch("cli.commands.check._repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", return_value=result),
    ):
        exit_code = check._run_tool("pytest", {"label": "TEST", "binary": "pytest"}, [])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "hint:===================== 2198 passed, 97 deselected in 41.52s" in captured.out


def test_check_tool_failure_prints_only_hint_and_details_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=1,
        stdout="very long output\nFAILED tests/test_x.py::test_y\n",
        stderr="traceback details\n",
    )
    with (
        patch("cli.commands.check._repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", return_value=result),
    ):
        exit_code = check._run_tool("pytest", {"label": "TEST", "binary": "pytest"}, [])

    captured = capsys.readouterr()
    details = tmp_path / ".dev-tools" / "pytest-details.txt"
    assert exit_code == 1
    assert "very long output" in details.read_text(encoding="utf-8")
    assert "very long output" not in captured.out
    assert "TEST:FAIL:1|details:.dev-tools/pytest-details.txt|hint:traceback details" in captured.out


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


def test_browser_help_explains_isolated_target() -> None:
    result = runner.invoke(main_app, ["browser", "--help"])

    assert result.exit_code == 0
    assert "Set SF_BROWSER_HOST to the approved isolated browser VM" in result.output
    assert "fail closed when SF_BROWSER_HOST is missing" in result.output
    assert "Use st vm list/status/ip/start" in result.output
    assert "SF_BROWSER_ALLOW_LOCAL=1" in result.output


def test_browser_subcommand_help_does_not_run_health() -> None:
    with patch("cli.commands.browser._print_health") as health:
        result = runner.invoke(main_app, ["browser", "health", "--help"])

    assert result.exit_code == 0
    assert "Set SF_BROWSER_HOST to the approved isolated browser VM" in result.output
    health.assert_not_called()


def test_vm_help_points_to_browser_target_workflow() -> None:
    result = runner.invoke(main_app, ["vm", "--help"])

    assert result.exit_code == 0
    assert "use st vm list/status/ip" in result.output
    assert "st browser with SF_BROWSER_HOST" in result.output


def test_service_help_explains_canonical_rebuild_path() -> None:
    result = runner.invoke(main_app, ["service", "--help"])

    assert result.exit_code == 0
    assert "Use rebuild/restart instead of raw" in result.output
    assert "health checks" in result.output


def test_check_help_explains_managed_gate() -> None:
    result = runner.invoke(main_app, ["check", "--help"])

    assert result.exit_code == 0
    assert "Use st check for repo gates" in result.output
    assert "Never run raw pytest" in result.output


def test_setup_help_explains_browser_isolation() -> None:
    result = runner.invoke(main_app, ["setup", "--help"])

    assert result.exit_code == 0
    assert "Browser setup defaults to" in result.output
    assert "server-local installs are debug-only" in result.output


def test_git_help_explains_managed_workflow() -> None:
    result = runner.invoke(main_app, ["git", "--help"])

    assert result.exit_code == 0
    assert "Low-level Git inspection" in result.output
    assert "st vcs doctor/reconcile" in result.output


def test_browser_host_requires_configured_target(monkeypatch) -> None:
    monkeypatch.setenv("SF_BROWSER_HOST", "")
    monkeypatch.delenv("SF_BROWSER_ALLOW_LOCAL", raising=False)

    with pytest.raises(typer.Exit):
        browser._host()


def test_browser_host_uses_env_without_probe(monkeypatch) -> None:
    monkeypatch.setenv("SF_BROWSER_HOST", "192.0.2.10")

    assert browser._host() == "192.0.2.10"


def test_browser_open_uses_repo_scoped_session(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_SESSION", raising=False)
    monkeypatch.delenv("ST_BROWSER_SESSION", raising=False)

    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._default_browser_session", return_value="st-repo-1234"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0)) as run_agent,
    ):
        result = runner.invoke(main_app, ["browser", "open", "https://example.com"])

    assert result.exit_code == 0
    assert run_agent.call_args_list[0].args[0] == [
        "--session",
        "st-repo-1234",
        "set",
        "viewport",
        "1600",
        "900",
    ]
    assert run_agent.call_args_list[1].args[0] == [
        "--session",
        "st-repo-1234",
        "open",
        "https://example.com",
    ]


def test_browser_open_preserves_explicit_session() -> None:
    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0)) as run_agent,
    ):
        result = runner.invoke(main_app, ["browser", "--session", "operator", "open", "https://example.com"])

    assert result.exit_code == 0
    assert run_agent.call_args_list[0].args[0] == [
        "--session",
        "operator",
        "set",
        "viewport",
        "1600",
        "900",
    ]
    assert run_agent.call_args_list[1].args[0] == [
        "--session",
        "operator",
        "open",
        "https://example.com",
    ]


def test_browser_check_closes_session_and_runs_reaper() -> None:
    calls: list[list[str]] = []

    def fake_run_agent(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[-1].startswith("JSON.stringify"):
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._run_browser_reaper") as reaper,
        patch("cli.commands.browser._run_agent", side_effect=fake_run_agent),
    ):
        result = runner.invoke(main_app, ["browser", "check", "https://example.com", "/tmp/check.png"])

    assert result.exit_code == 0
    assert calls[-1][2:] == ["close"]
    reaper.assert_called_once()


def test_browser_check_treats_screenshot_timeout_as_warning(tmp_path: Path) -> None:
    def fake_run_agent(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if "screenshot" in args:
            return subprocess.CompletedProcess(args, 124, stdout="", stderr="Operation timed out")
        if args[-1].startswith("JSON.stringify(performance"):
            return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")
        if args[-1].startswith("JSON.stringify"):
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with (
        patch("cli.commands.browser.current_root", return_value=tmp_path),
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._run_agent", side_effect=fake_run_agent),
    ):
        result = runner.invoke(main_app, ["browser", "check", "https://example.com", "/tmp/check.png"])

    assert result.exit_code == 0
    assert "BROWSER_CHECK:OK|errors=0|warnings=0|network=0|command_warnings=3" in result.output
    details = tmp_path / ".dev-tools" / "browser-check-details.txt"
    assert "Browser command warnings (3):" in details.read_text(encoding="utf-8")


def test_browser_large_forwarded_output_goes_to_details_file(tmp_path: Path) -> None:
    output = "\n".join(f"node {index}" for index in range(45))
    with (
        patch("cli.commands.browser.current_root", return_value=tmp_path),
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr="")),
    ):
        result = runner.invoke(main_app, ["browser", "snapshot"])

    details = tmp_path / ".dev-tools" / "browser-snapshot-details.txt"
    assert result.exit_code == 0
    assert details.read_text(encoding="utf-8") == output
    assert "node 0" not in result.output
    assert "BROWSER:OK:0|lines=45|details:.dev-tools/browser-snapshot-details.txt" in result.output


def test_docker_large_output_goes_to_details_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    output = "\n".join(f"layer {index}" for index in range(45))
    result = subprocess.CompletedProcess(["docker", "compose", "pull"], 0, stdout=output, stderr="")
    with patch("cli.commands.docker.subprocess.run", return_value=result):
        returned = docker._run(["docker", "compose", "pull"])

    captured = capsys.readouterr()
    details = tmp_path / ".dev-tools" / "docker-docker-compose-pull-details.txt"
    assert returned is result
    assert details.read_text(encoding="utf-8") == output
    assert "layer 0" not in captured.out
    assert "DOCKER:OK:0|lines=45|details:.dev-tools/docker-docker-compose-pull-details.txt" in captured.out


def test_setup_browser_refuses_server_local_install(monkeypatch) -> None:
    monkeypatch.delenv("ST_SETUP_BROWSER_ALLOW_SERVER_INSTALL", raising=False)

    with patch("cli.commands.setup.confirm_gate"):
        result = runner.invoke(setup.app, ["browser", "--confirm", "abc12345"])

    assert result.exit_code == 2
    assert "Refusing server-local browser install" in result.output


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
