"""Tests for canonical st operator commands."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from cli.commands import browser, check, db, docker, service, setup, vm
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


def test_service_status_accepts_project_option_alias() -> None:
    with (
        patch("cli.commands.service._load", return_value=_project()) as load,
        patch("cli.commands.service.service_ops.service_state", return_value="active"),
    ):
        result = runner.invoke(service.app, ["status", "--project", "summitflow"])

    assert result.exit_code == 0
    load.assert_called_once_with("summitflow")


def test_service_status_rejects_conflicting_project_inputs() -> None:
    result = runner.invoke(service.app, ["status", "summitflow", "--project", "portfolio-ai"])

    assert result.exit_code == 1
    assert "Pass project either as PROJECT or --project/-P" in result.output


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


def test_kill_port_parses_ss_listener_pids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    port_checks = iter([True, False])

    def fake_capture(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[0] == "ss":
            return subprocess.CompletedProcess(
                command,
                0,
                'LISTEN users:(("uvicorn",pid=556775,fd=19),("uvicorn",pid=1725536,fd=19))',
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(service_ops, "_port_open", lambda _port: next(port_checks))
    monkeypatch.setattr(service_ops, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(service_ops, "capture", fake_capture)

    assert service_ops._kill_port(8001) is True
    assert ["kill", "556775"] in calls
    assert ["kill", "1725536"] in calls


def test_restart_service_fails_if_old_pid_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    run_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> int:
        run_calls.append(command)
        return 0

    monkeypatch.setattr(service_ops, "service_exists", lambda _service: True)
    monkeypatch.setattr(service_ops, "_systemctl_value", lambda _service, _key: "")
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda _service: 556775)
    monkeypatch.setattr(service_ops, "_wait_service_inactive", lambda _service, timeout=8.0: True)
    monkeypatch.setattr(service_ops, "_pid_alive", lambda pid: pid == 556775)
    monkeypatch.setattr(service_ops, "_kill_port", lambda _port: True)
    monkeypatch.setattr(service_ops, "capture", lambda command, cwd=None: subprocess.CompletedProcess(command, 0, "", ""))
    monkeypatch.setattr(service_ops, "run", fake_run)

    assert service_ops.restart_service("summitflow-backend.service", port=8001) == 1
    assert ["systemctl", "--user", "start", "summitflow-backend.service"] not in run_calls


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


def test_db_detail_name_hashes_query_without_literals() -> None:
    name = db._psql_detail_name("summitflow", "query", sql="SELECT * FROM events WHERE message = 'secret'")

    assert name.startswith("db-summitflow-query-")
    assert "secret" not in name
    assert len(name.rsplit("-", 1)[1]) == 8


def test_db_url_uses_canonical_project_resolver() -> None:
    resolved = "postgresql://summitflow_app:pw@localhost/summitflow"

    with patch("cli.commands.db.project_db_url", return_value=resolved) as resolver:
        assert db._db_url("a-term") == resolved

    resolver.assert_called_once_with("a-term")


def test_run_psql_serializes_before_subprocess_and_sets_app_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    emitted: list[tuple[Path, str, str, subprocess.CompletedProcess[str]]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        assert (tmp_path / ".dev-tools" / "db-summitflow-psql.lock").exists()
        return subprocess.CompletedProcess(args, 0, "ok\n", "")

    monkeypatch.setattr(db, "_db_url", lambda project: f"postgresql:///{project}")
    monkeypatch.setattr(db, "_details_root", lambda _project: tmp_path)
    monkeypatch.setattr(db.subprocess, "run", fake_run)
    monkeypatch.setattr(
        db,
        "emit_result_or_details",
        lambda root, name, label, result: emitted.append((root, name, label, result)),
    )

    assert db._run_psql("summitflow", "SELECT 1", detail_name="db-summitflow-query-test") == 0

    assert calls[0][0] == ["psql", "postgresql:///summitflow", "-c", "SELECT 1"]
    kwargs = calls[0][1]
    env = kwargs["env"]
    assert isinstance(env, dict)
    env = cast(dict[str, str], env)
    assert env["PGAPPNAME"] == "st-db-summitflow"
    assert emitted[0][1] == "db-summitflow-query-test"


def test_db_schema_uses_command_specific_detail_name() -> None:
    with (
        patch("cli.commands.db._detect_project", return_value="summitflow"),
        patch("cli.commands.db._run_psql", return_value=0) as run_psql,
    ):
        result = runner.invoke(main_app, ["db", "schema", "agent_tools"])

    assert result.exit_code == 0
    assert run_psql.call_args.kwargs["detail_name"] == "db-summitflow-schema-agent_tools"


def test_autonomous_status_reads_settings() -> None:
    settings = {"enabled": True, "upkeep_enabled": False}
    with patch("cli.commands.autonomous.STClient") as client_cls:
        client_cls.return_value.get_autonomous_settings.return_value = settings
        result = runner.invoke(main_app, ["autonomous", "status"])

    assert result.exit_code == 0
    assert '"enabled": true' in result.output
    client_cls.return_value.get_autonomous_settings.assert_called_once_with()


def test_autonomous_enable_wires_work_pickup_and_upkeep_schedules() -> None:
    settings = {"enabled": True, "upkeep_enabled": True}
    with patch("cli.commands.autonomous.STClient") as client_cls:
        client = client_cls.return_value
        client.update_autonomous_settings.return_value = settings
        client.update_autonomous_schedule.side_effect = [
            {"schedule_id": "work_pickup", "enabled": True},
            {"schedule_id": "task_generation", "enabled": True},
        ]

        result = runner.invoke(main_app, ["autonomous", "enable"])

    assert result.exit_code == 0
    client.update_autonomous_settings.assert_called_once_with(enabled=True, upkeep_enabled=True)
    assert client.update_autonomous_schedule.call_args_list[0].args == ("work_pickup",)
    assert client.update_autonomous_schedule.call_args_list[0].kwargs == {"enabled": True}
    assert client.update_autonomous_schedule.call_args_list[1].args == ("task_generation",)
    assert client.update_autonomous_schedule.call_args_list[1].kwargs == {"enabled": True}
    assert '"schedule_id": "work_pickup"' in result.output


def test_autonomous_schedules_lists_schedule_states() -> None:
    schedules = [{"schedule_id": "work_pickup", "enabled": True}]
    with patch("cli.commands.autonomous.STClient") as client_cls:
        client_cls.return_value.list_autonomous_schedules.return_value = schedules
        result = runner.invoke(main_app, ["autonomous", "schedules"])

    assert result.exit_code == 0
    assert '"schedule_id": "work_pickup"' in result.output
    client_cls.return_value.list_autonomous_schedules.assert_called_once_with()


def test_autonomous_upkeep_runs_discovery_cycle() -> None:
    with patch("cli.commands.autonomous.STClient") as client_cls:
        client_cls.return_value.run_routine_upkeep.return_value = {
            "project_id": "summitflow",
            "status": "completed",
            "tasks_created": 2,
        }
        result = runner.invoke(main_app, ["autonomous", "upkeep"])

    assert result.exit_code == 0
    assert '"tasks_created": 2' in result.output
    client_cls.return_value.run_routine_upkeep.assert_called_once_with()


def test_check_runs_native_tool() -> None:
    with (
        patch("cli.commands.check._tool_configs", return_value={"ruff": {"label": "LINT", "binary": "ruff"}}),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "ruff"])

    assert result.exit_code == 0
    run_tool.assert_called_once()


def test_check_boots_when_unrelated_command_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import cli.main as main_module

    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "cli.commands.browser":
            raise NameError("name 're' is not defined")
        return real_import_module(name, package)

    with monkeypatch.context() as ctx:
        ctx.setattr(importlib, "import_module", fake_import_module)
        reloaded = importlib.reload(main_module)
        with (
            patch("cli.commands.check._tool_configs", return_value={"ruff": {"label": "LINT", "binary": "ruff"}}),
            patch("cli.commands.check._run_tool", return_value=0) as run_tool,
        ):
            result = runner.invoke(reloaded.app, ["check", "ruff"])

    importlib.reload(main_module)

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


def test_check_bare_changed_only_defaults_to_quick() -> None:
    configs = {
        "pytest": {"label": "TEST", "binary": "pytest", "pass_path": False},
        "tsc": {"label": "TSC", "binary": "npx", "args": "tsc --noEmit", "pass_path": False},
    }
    with (
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._changed_files", return_value=["config.toml"]),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "--changed-only"])

    assert result.exit_code == 0
    assert "TEST:SKIP:pytest:no_relevant_changed_paths" in result.output
    assert "TSC:SKIP:tsc:no_relevant_changed_paths" in result.output
    run_tool.assert_not_called()


def test_check_changed_only_skips_pytest_for_app_only_python_changes() -> None:
    configs = {
        "pytest": {"label": "TEST", "binary": "pytest", "pass_path": False},
    }
    with (
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._changed_files", return_value=["backend/app/api/tasks.py"]),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    assert "TEST:SKIP:pytest:no_relevant_changed_paths" in result.output
    run_tool.assert_not_called()


def test_check_changed_only_targets_changed_pytest_files() -> None:
    configs = {
        "pytest": {
            "label": "TEST",
            "binary": "pytest",
            "working_dir": "test",
            "pass_path": False,
        },
    }
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=Path("/repo")),
        patch("cli.commands.check.Path.exists", return_value=True),
        patch("cli.commands.check.Path.is_file", return_value=True),
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._changed_files", return_value=["backend/tests/cli/test_check.py"]),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    run_tool.assert_called_once_with("pytest", configs["pytest"], ["tests/cli/test_check.py"])


def test_check_changed_only_uses_changed_files_override(monkeypatch) -> None:
    monkeypatch.setenv(
        "ST_CHECK_CHANGED_FILES",
        "frontend/components/runtime/ServiceCard.tsx\nbackend/app/main.py",
    )

    assert check._changed_files(Path("/repo")) == [
        "backend/app/main.py",
        "frontend/components/runtime/ServiceCard.tsx",
    ]


def test_check_changed_only_targets_biome_override_paths(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "frontend" / "components" / "runtime" / "ServiceCard.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    configs = {
        "biome": {
            "label": "BIOME",
            "binary": "npx",
            "args": "biome check . --max-diagnostics=100",
            "working_dir": "frontend",
            "pass_path": True,
        },
    }
    monkeypatch.setenv("ST_CHECK_CHANGED_FILES", "frontend/components/runtime/ServiceCard.tsx")
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    run_tool.assert_called_once_with(
        "biome",
        configs["biome"],
        ["components/runtime/ServiceCard.tsx"],
    )


def test_check_changed_only_runs_broad_path_tool_for_config_changes() -> None:
    configs = {
        "biome": {"label": "BIOME", "binary": "biome", "args": "check .", "pass_path": True},
    }
    with (
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._changed_files", return_value=["package.json"]),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    run_tool.assert_called_once_with("biome", configs["biome"], [])


def test_check_changed_only_runs_broad_pytest_for_config_changes() -> None:
    configs = {
        "pytest": {"label": "TEST", "binary": "pytest", "pass_path": False},
    }
    with (
        patch("cli.commands.check._tool_configs", return_value=configs),
        patch("cli.commands.check._changed_files", return_value=["pyproject.toml"]),
        patch("cli.commands.check._run_tool", return_value=0) as run_tool,
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    run_tool.assert_called_once_with("pytest", configs["pytest"], [])


def test_check_architecture_blocks_raw_subprocess_in_web_app(tmp_path: Path) -> None:
    target = tmp_path / "backend" / "app" / "api" / "unsafe.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import subprocess\n\ndef f():\n    return subprocess.run(['hostname'])\n",
        encoding="utf-8",
    )

    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value={}),
        patch("cli.commands.check._changed_files", return_value=["backend/app/api/unsafe.py"]),
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 1
    assert "ARCH:FAIL:1" in result.output
    assert "backend/app/api/unsafe.py:4 raw subprocess.run" in result.output


def test_check_architecture_blocks_async_subprocess_in_web_app(tmp_path: Path) -> None:
    target = tmp_path / "backend" / "app" / "services" / "unsafe_async.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import asyncio\n\nasync def f():\n    return await asyncio.create_subprocess_exec('hostname')\n",
        encoding="utf-8",
    )

    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value={}),
        patch("cli.commands.check._changed_files", return_value=["backend/app/services/unsafe_async.py"]),
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 1
    assert "backend/app/services/unsafe_async.py:4 raw asyncio.create_subprocess_exec" in result.output


def test_check_architecture_allows_safe_subprocess_wrapper(tmp_path: Path) -> None:
    target = tmp_path / "backend" / "app" / "api" / "safe.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "from app.utils import safe_subprocess\n\ndef f():\n    return safe_subprocess.run(['hostname'])\n",
        encoding="utf-8",
    )

    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check._tool_configs", return_value={}),
        patch("cli.commands.check._changed_files", return_value=["backend/app/api/safe.py"]),
    ):
        result = runner.invoke(main_app, ["check", "--quick", "--changed-only"])

    assert result.exit_code == 0
    assert "ARCH:OK:architecture" in result.output


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
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
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
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
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


def test_check_biome_explicit_paths_replace_default_dot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    biome = frontend / "node_modules" / ".bin" / "biome"
    biome.parent.mkdir(parents=True)
    biome.write_text("#!/bin/sh\n", encoding="utf-8")
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="",
        stderr="",
    )
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", return_value=completed) as run,
    ):
        exit_code = check._run_tool(
            "biome",
            {
                "label": "BIOME",
                "binary": "npx",
                "args": "biome check . --max-diagnostics=100",
                "working_dir": "frontend",
            },
            ["components/runtime/ServiceCard.tsx"],
        )

    assert exit_code == 0
    command = run.call_args.args[0]
    assert command == [
        str(biome),
        "check",
        "--max-diagnostics=100",
        "components/runtime/ServiceCard.tsx",
    ]
    assert "BIOME:OK:0" in capsys.readouterr().out


def test_check_tool_output_goes_to_details_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=0,
        stdout="line 1\n2187 passed in 19.87s\n",
        stderr="",
    )
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", return_value=result),
    ):
        exit_code = check._run_tool("pytest", {"label": "TEST", "binary": "pytest"}, [])

    captured = capsys.readouterr()
    details = tmp_path / ".dev-tools" / "pytest-details.txt"
    assert exit_code == 0
    assert details.read_text(encoding="utf-8") == "line 1\n2187 passed in 19.87s\n"
    assert "line 1" not in captured.out
    assert "TEST:OK:0|details:.dev-tools/pytest-details.txt|hint:2187 passed in 19.87s" in captured.out


def test_check_pytest_scoped_paths_disable_configured_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = subprocess.CompletedProcess(args=["pytest"], returncode=0, stdout="1 passed\n", stderr="")
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", return_value=result) as run,
    ):
        exit_code = check._run_tool(
            "pytest",
            {"label": "TEST", "binary": "pytest", "args": "--cov=app --cov-fail-under=51"},
            ["tests/test_prediction.py"],
        )

    command = run.call_args.args[0]
    assert exit_code == 0
    assert "--no-cov" in command
    assert command.index("--no-cov") < command.index("tests/test_prediction.py")
    assert "TEST:OK:0" in capsys.readouterr().out


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
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
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
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
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


def test_db_tables_counts_uses_exact_counts_not_pg_stats() -> None:
    sql = db._tables_counts_sql()

    assert "query_to_xml" in sql
    assert "count(*)" in sql.lower()
    assert "information_schema.tables" in sql
    assert "n_live_tup" not in sql
    assert "pg_stat_user_tables" not in sql


def test_browser_health_uses_native_health() -> None:
    with patch("cli.commands.browser._print_health") as health:
        result = runner.invoke(main_app, ["browser", "--proxmox", "health"])

    assert result.exit_code == 0
    health.assert_called_once()


def test_browser_health_defaults_to_local_ai() -> None:
    with patch("cli.commands.browser._print_local_ai_health") as health:
        result = runner.invoke(main_app, ["browser", "health"])

    assert result.exit_code == 0
    health.assert_called_once()


def test_browser_help_explains_isolated_target() -> None:
    result = runner.invoke(main_app, ["browser", "--help"])

    assert result.exit_code == 0
    assert "Plain st browser commands use local system Chrome profile AI." in result.output
    assert "Force Proxmox/VM with --proxmox" in result.output
    assert "st browser url <project>" in result.output
    assert "st browser check a-term" in result.output
    assert "st browser --local-ai open portfolio-ai" in result.output
    assert "Override VM with ST_BROWSER_HOST" in result.output
    assert "ST_BROWSER_DISABLE_DEFAULT_VM_HOST=1" in result.output
    assert "ST_BROWSER_ALLOW_LOCAL=1" in result.output


def test_browser_subcommand_help_does_not_run_health() -> None:
    with patch("cli.commands.browser._print_health") as health:
        result = runner.invoke(main_app, ["browser", "health", "--help"])

    assert result.exit_code == 0
    assert "Plain st browser commands use local system Chrome profile AI." in result.output
    health.assert_not_called()


def test_vm_help_points_to_browser_target_workflow() -> None:
    result = runner.invoke(main_app, ["vm", "--help"])

    assert result.exit_code == 0
    assert "Use for browser/test VM status" in result.output
    assert "st browser uses the default browser VM" in result.output


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


def test_browser_host_uses_default_vm_when_host_missing(monkeypatch) -> None:
    monkeypatch.setenv("ST_BROWSER_HOST", "")
    monkeypatch.delenv("ST_BROWSER_DEFAULT_HOST", raising=False)
    monkeypatch.delenv("ST_BROWSER_DISABLE_DEFAULT_VM_HOST", raising=False)
    monkeypatch.delenv("ST_BROWSER_ALLOW_LOCAL", raising=False)

    with patch("cli.commands.browser._default_browser_vm_host", return_value="192.0.2.88") as default_host:
        assert browser._host() == "192.0.2.88"

    default_host.assert_called_once()


def test_browser_host_can_disable_default_vm(monkeypatch) -> None:
    monkeypatch.setenv("ST_BROWSER_HOST", "")
    monkeypatch.delenv("ST_BROWSER_DEFAULT_HOST", raising=False)
    monkeypatch.setenv("ST_BROWSER_DISABLE_DEFAULT_VM_HOST", "1")
    monkeypatch.delenv("ST_BROWSER_ALLOW_LOCAL", raising=False)

    with pytest.raises(typer.Exit):
        browser._host()


def test_browser_host_uses_env_without_probe(monkeypatch) -> None:
    monkeypatch.setenv("ST_BROWSER_HOST", "192.0.2.10")

    with patch("cli.commands.browser._default_browser_vm_host") as default_host:
        assert browser._host() == "192.0.2.10"

    default_host.assert_not_called()


def test_browser_vm_ip_selection_prefers_management_network() -> None:
    output = "\n".join(["172.24.0.1", "10.1.2.3", "192.168.8.234"])

    assert browser._select_browser_vm_ip(output, {}) == "192.168.8.234"


def test_browser_vm_ip_selection_honors_prefix() -> None:
    output = "\n".join(["192.168.8.234", "10.1.2.3"])

    assert browser._select_browser_vm_ip(output, {"ST_BROWSER_VM_IP_PREFIX": "10."}) == "10.1.2.3"


def test_browser_url_resolves_project() -> None:
    route = SimpleNamespace(url="https://terminal.summitflow.dev/", project_id="a-term", source="hosts.browser_frontend")
    with patch("cli.commands.browser.resolve_browser_project_route", return_value=route):
        result = runner.invoke(main_app, ["browser", "url", "terminal"])

    assert result.exit_code == 0
    assert "https://terminal.summitflow.dev/" in result.output
    assert "a-term hosts.browser_frontend" in result.output


def test_browser_endpoint_prints_canonical_http_url() -> None:
    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser-vm"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser-vm/devtools/browser/abc"),
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "endpoint"])

    assert result.exit_code == 0
    assert result.output == "http://browser-vm:9222\n"


def test_browser_endpoint_prints_canonical_ws_url() -> None:
    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser-vm"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser-vm/devtools/browser/abc"),
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "endpoint", "--ws"])

    assert result.exit_code == 0
    assert result.output == "ws://browser-vm/devtools/browser/abc\n"


def test_browser_auto_open_prefers_local_ai_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_PROFILE", raising=False)
    monkeypatch.delenv("AGENT_BROWSER_EXECUTABLE_PATH", raising=False)
    with (
        patch("cli.commands.browser._system_chrome_path", return_value="/usr/bin/google-chrome-stable"),
        patch("cli.commands.browser.resolve_browser_location", return_value="http://app.lan:3005/"),
        patch("cli.commands.browser._select_port") as select_port,
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as run_agent,
    ):
        result = runner.invoke(main_app, ["browser", "open", "portfolio-ai"])

    assert result.exit_code == 0
    select_port.assert_not_called()
    assert run_agent.call_args.args[0] == [
        "--profile",
        "AI",
        "--executable-path",
        "/usr/bin/google-chrome-stable",
        "--headed",
        "open",
        "http://app.lan:3005/",
    ]


def test_browser_force_proxmox_skips_local_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_SESSION", raising=False)
    monkeypatch.delenv("ST_BROWSER_SESSION", raising=False)
    with (
        patch("cli.commands.browser._system_chrome_path", return_value="/usr/bin/google-chrome-stable"),
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._default_browser_session", return_value="st-repo-1234"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0)) as run_agent,
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "open", "https://example.com"])

    assert result.exit_code == 0
    assert run_agent.call_args_list[1].kwargs["cdp"] == "ws://browser"
    assert run_agent.call_args_list[1].args[0] == [
        "--session",
        "st-repo-1234",
        "open",
        "https://example.com",
    ]


def test_browser_select_port_honors_explicit_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ST_BROWSER_HOST", "192.0.2.10")
    monkeypatch.setenv("ST_BROWSER_PORT", "9333")

    with patch("cli.commands.browser._engine_up", return_value=True) as engine_up:
        assert browser._select_port("chrome") == 9333

    engine_up.assert_called_once_with(9333, host="192.0.2.10")


def test_browser_open_uses_repo_scoped_session(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_SESSION", raising=False)
    monkeypatch.delenv("ST_BROWSER_SESSION", raising=False)

    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._default_browser_session", return_value="st-repo-1234"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._close_blank_browser_targets") as close_blank,
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0)) as run_agent,
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "open", "https://example.com"])

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
    close_blank.assert_not_called()


def test_browser_open_blocks_loopback_url_before_selecting_browser(monkeypatch) -> None:
    monkeypatch.delenv("ST_BROWSER_CONFIRM_LOCAL_URL", raising=False)

    with patch("cli.commands.browser._select_port") as select_port:
        result = runner.invoke(main_app, ["browser", "--proxmox", "open", "http://127.0.0.1:3000/money"])

    assert result.exit_code == 2
    assert "LOCAL_BROWSER_URL_BLOCKED" in result.output
    assert "browser VM 100" in result.output
    assert "st browser url <project>" in result.output
    assert "ST_BROWSER_CONFIRM_LOCAL_URL=" in result.output
    select_port.assert_not_called()


def test_browser_open_resolves_project_target(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_SESSION", raising=False)
    monkeypatch.delenv("ST_BROWSER_SESSION", raising=False)

    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._default_browser_session", return_value="st-repo-1234"),
        patch("cli.commands.browser.resolve_browser_location", return_value="https://terminal.summitflow.dev/"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0)) as run_agent,
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "open", "a-term"])

    assert result.exit_code == 0
    assert run_agent.call_args_list[1].args[0] == [
        "--session",
        "st-repo-1234",
        "open",
        "https://terminal.summitflow.dev/",
    ]


def test_browser_open_preserves_explicit_session() -> None:
    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._close_blank_browser_targets") as close_blank,
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0)) as run_agent,
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "--session", "operator", "open", "https://example.com"])

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
    close_blank.assert_not_called()


def test_browser_snapshot_prunes_remote_blank_targets(tmp_path: Path) -> None:
    with (
        patch("cli.commands.browser.current_root", return_value=tmp_path),
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser"),
        patch("cli.commands.browser._run_browser_reaper"),
        patch("cli.commands.browser._close_blank_browser_targets") as close_blank,
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0, stdout="(empty page)", stderr="")),
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "snapshot"])

    assert result.exit_code == 0
    close_blank.assert_called_once_with("browser", 9222)


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
        patch("cli.lib.browser_check.browser_page_target_ids", side_effect=[{"before"}, {"before", "after"}]),
        patch("cli.lib.browser_check.close_browser_targets") as close_targets,
        patch("cli.commands.browser._run_agent", side_effect=fake_run_agent),
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "check", "https://example.com", "/tmp/check.png"])

    assert result.exit_code == 0
    assert calls[-1][2:] == ["close"]
    reaper.assert_called_once()
    close_targets.assert_called_once_with("browser", 9222, {"after"})


def test_browser_check_blocks_localhost_url_before_selecting_browser(monkeypatch) -> None:
    monkeypatch.delenv("ST_BROWSER_CONFIRM_LOCAL_URL", raising=False)

    with patch("cli.commands.browser._select_port") as select_port:
        result = runner.invoke(main_app, ["browser", "--proxmox", "check", "http://localhost:3000/money", "/tmp/check.png"])

    assert result.exit_code == 2
    assert "LOCAL_BROWSER_URL_BLOCKED" in result.output
    assert "target_host=localhost:3000" in result.output
    assert "localhost/127.0.0.1 is that VM" in result.output
    assert "ST_BROWSER_CONFIRM_LOCAL_URL=" in result.output
    select_port.assert_not_called()


def test_browser_local_url_confirmation_token_allows_intentional_target(monkeypatch) -> None:
    target = "http://localhost:3000/money?token=secret"
    message = browser._local_browser_url_error(target)

    assert message is not None
    assert "target_host=localhost:3000" in message
    assert "token=secret" not in message

    monkeypatch.setenv("ST_BROWSER_CONFIRM_LOCAL_URL", browser._local_url_confirmation_token(target))

    assert browser._local_browser_url_error(target) is None


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
        patch("cli.lib.browser_check.browser_page_target_ids", return_value=set()),
        patch("cli.lib.browser_check.close_browser_targets"),
        patch("cli.commands.browser._run_agent", side_effect=fake_run_agent),
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "check", "https://example.com", "/tmp/check.png"])

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
        patch("cli.commands.browser._close_blank_browser_targets"),
        patch("cli.commands.browser._run_agent", return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr="")),
    ):
        result = runner.invoke(main_app, ["browser", "--proxmox", "snapshot"])

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
