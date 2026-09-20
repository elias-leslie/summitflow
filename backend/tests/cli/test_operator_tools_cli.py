"""Tests for canonical st operator commands."""

from __future__ import annotations

import importlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from cli.commands import browser, check, db, docker, service, setup, vm
from cli.lib import service_ops
from cli.lib.proxmox import ProxmoxClient, ProxmoxConfig
from cli.lib.service_ops import ProjectServices
from cli.main import app as main_app

runner = CliRunner()


def test_db_honors_root_project_flag_without_cwd_override() -> None:
    from cli.config import set_project_override
    try:
        with (
            patch("cli.commands.db.find_project_by_cwd", return_value={"id": "summitflow"}),
            patch("cli.commands.db._run_psql", return_value=0) as query,
        ):
            result = runner.invoke(main_app, ["-P", "agent-hub", "db", "query", "SELECT 1"])
        assert result.exit_code == 0, result.output
        assert query.call_args.args[0] == "agent-hub"
    finally:
        set_project_override(None)


def test_nested_db_query_help_never_opens_a_database() -> None:
    with patch("cli.commands.db._run_psql") as query:
        result = runner.invoke(main_app, ["db", "query", "--help"])
    assert result.exit_code == 0, result.output
    assert "query" in result.output and "Usage:" in result.output
    query.assert_not_called()


def test_test_database_setup_can_target_only_jobinator() -> None:
    with (
        patch("cli.commands.setup._preview"),
        patch("app.tasks.backup_native_infra._find_compose_container", return_value="test-postgres"),
        patch("cli.commands.setup._run", return_value=0) as run,
    ):
        result = runner.invoke(setup.app, ["test-dbs", "--project", "jobinator-4000"])
    assert result.exit_code == 0
    assert run.call_count == 3
    assert run.call_args_list[0].args[0] == [
        "docker", "exec", "-i", "test-postgres", "createdb", "-U", "admin",
        "-O", "jobinator_app", "jobinator_test",
    ]


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
        patch("cli.commands.service.service_ops.sync_backend", return_value=0),
        patch("cli.commands.service.service_ops.service_state", return_value="active"),
        patch("cli.commands.service.service_ops.build_frontend", return_value=0),
        patch("cli.commands.service.service_ops.run_migrations", return_value=0),
        patch("cli.commands.service.service_ops.sync_systemd_units", return_value=0),
        patch("cli.commands.service.service_ops.restart_service", return_value=0) as restart,
        patch("cli.commands.service.service_ops.verify_health", return_value=0),
        patch("cli.commands.service.service_ops.sync_seeds", return_value=0),
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
        patch("cli.lib.service_ops.run", return_value=0) as run,
    ):
        assert service_ops.build_frontend(project) == 0

    assert run.call_args_list[0].args[0] == ["pnpm", "install", "--frozen-lockfile"]
    run.assert_called_with(["pnpm", "build"], cwd=project.frontend_dir, quiet_success=True)


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


def test_run_psql_read_only_uses_one_protected_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "ok\n", "")

    monkeypatch.setattr(db, "_db_url", lambda project: f"postgresql:///{project}")
    monkeypatch.setattr(db, "_details_root", lambda _project: tmp_path)
    monkeypatch.setattr(db.subprocess, "run", fake_run)
    monkeypatch.setattr(db, "emit_result_or_details", lambda *_args: None)

    assert db._run_psql("summitflow", "SELECT 1", read_only=True) == 0

    assert calls == [
        [
            "psql",
            "postgresql:///summitflow",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "BEGIN TRANSACTION READ ONLY;",
            "-c",
            "SELECT 1",
            "-c",
            "ROLLBACK;",
        ]
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT '; DELETE FROM tasks' AS example; -- harmless text",
        'SELECT "update" FROM tasks',
        "WITH recent AS (SELECT id FROM tasks) SELECT * FROM recent",
        "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM tasks",
        "SHOW transaction_read_only",
        "TABLE tasks",
        "VALUES (1), (2)",
        "SELECT $$semi; UPDATE tasks$$",
        "/* nested /* comment */ remains safe */ SELECT 1",
    ],
)
def test_db_query_accepts_single_diagnostic_statement(sql: str) -> None:
    assert db._is_read_query(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1;;",
        "WITH changed AS (DELETE FROM tasks RETURNING *) SELECT * FROM changed",
        "WITH changed AS (UPDATE tasks SET title = 'x' RETURNING *) SELECT * FROM changed",
        "SELECT * FROM tasks FOR UPDATE",
        "SELECT * FROM tasks FOR NO KEY UPDATE",
        "SELECT * FROM tasks FOR SHARE",
        "SELECT * INTO task_copy FROM tasks",
        "CREATE TEMP TABLE copy AS SELECT * FROM tasks",
        "EXPLAIN ANALYZE DELETE FROM tasks",
        "\\! echo unsafe",
        "SELECT 'unterminated",
        "/* unterminated SELECT 1",
    ],
)
def test_db_query_rejects_write_capable_or_multiple_statements(sql: str) -> None:
    assert not db._is_read_query(sql)


def test_db_query_executes_validated_sql_in_read_only_transaction() -> None:
    with (
        patch("cli.commands.db._detect_project", return_value="summitflow"),
        patch("cli.commands.db._run_psql", return_value=0) as run_psql,
    ):
        result = runner.invoke(main_app, ["db", "query", "EXPLAIN SELECT 1"])

    assert result.exit_code == 0
    assert run_psql.call_args.args == ("summitflow", "EXPLAIN SELECT 1")
    assert run_psql.call_args.kwargs["read_only"] is True


def test_db_query_rejects_unsafe_sql_before_opening_connection() -> None:
    with (
        patch("cli.commands.db._detect_project", return_value="summitflow"),
        patch("cli.commands.db._run_psql") as run_psql,
    ):
        result = runner.invoke(main_app, ["db", "query", "SELECT 1; DELETE FROM tasks"])

    assert result.exit_code == 1
    assert "Write operations blocked" in result.output
    run_psql.assert_not_called()


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


def test_check_changed_only_runs_pytest_for_app_only_python_changes() -> None:
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
    assert "TEST:SKIP" not in result.output
    run_tool.assert_called_once_with("pytest", configs["pytest"], [])


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


def test_check_missing_binary_skips_when_no_project_env(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No venv anywhere (e.g. pytest in a config repo): skip, don't fail."""
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", side_effect=FileNotFoundError("pytest")),
    ):
        exit_code = check._run_tool("pytest", {"label": "TEST", "binary": "pytest"}, [])

    assert exit_code == 0
    assert "TEST:SKIP:pytest:tool_not_installed" in capsys.readouterr().out


def test_check_missing_binary_fails_when_project_env_exists(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A venv exists but the binary is gone: broken env stays a failure."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    with (
        patch("cli.commands.check._resolve_repo_root", return_value=tmp_path),
        patch("cli.commands.check.subprocess.run", side_effect=FileNotFoundError("pytest")),
    ):
        exit_code = check._run_tool("pytest", {"label": "TEST", "binary": "pytest"}, [])

    captured = capsys.readouterr()
    assert exit_code == 127
    assert "TEST:FAIL:127" in captured.out


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


def test_db_creates_manual_migration_without_autogenerate() -> None:
    with (
        patch("cli.commands.db._detect_project", return_value="portfolio-ai"),
        patch("cli.commands.db._alembic", return_value=0) as alembic,
    ):
        result = runner.invoke(
            main_app,
            ["db", "migrate", "create-manual", "prepare squashed baseline"],
        )

    assert result.exit_code == 0
    alembic.assert_called_once_with(
        "portfolio-ai",
        ["revision", "-m", "prepare squashed baseline"],
    )


def test_db_migration_url_override_targets_ephemeral_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_url = "postgresql://portfolio_app:secret@localhost/portfolio_ai_verify"
    monkeypatch.setenv("ST_DB_MIGRATION_URL", migration_url)
    monkeypatch.setenv("PORTFOLIO_DB_URL", "postgresql://production")
    completed = subprocess.CompletedProcess(args=["alembic"], returncode=0, stdout="", stderr="")

    with (
        patch("cli.commands.db._migration_dir", return_value=tmp_path),
        patch("cli.commands.db.subprocess.run", return_value=completed) as run,
        patch("cli.commands.db.emit_result_or_details"),
    ):
        exit_code = db._alembic("portfolio-ai", ["upgrade", "head"])

    assert exit_code == 0
    migration_env = run.call_args.kwargs["env"]
    assert migration_env["PORTFOLIO_DB_URL"] == migration_url
    assert "ST_DB_MIGRATION_URL" not in migration_env


def test_db_tables_counts_uses_exact_counts_not_pg_stats() -> None:
    sql = db._tables_counts_sql()

    assert "query_to_xml" in sql
    assert "count(*)" in sql.lower()
    assert "information_schema.tables" in sql
    assert "n_live_tup" not in sql
    assert "pg_stat_user_tables" not in sql


def _browser_context(tmp_path: Path) -> dict[str, object]:
    return {
        "contract_version": 1,
        "project_id": "fixture",
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
        "api_base": "http://localhost:8001/api",
        "agent_hub_url": "http://localhost:8003",
        "output": {"human": False, "compact": True, "progress_only": False},
    }


@contextmanager
def _available_browser_lock():
    yield True


def _registered_browser_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
) -> tuple[int, dict[str, Any]]:
    captured: list[list[str]] = []
    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/usr/bin/agent-browser")
    monkeypatch.setattr(
        "cli.lib.browser_policy.system_chrome_path",
        lambda env=None: "/usr/bin/google-chrome-stable",
    )
    monkeypatch.setattr(browser, "_local_ai_command_lock", _available_browser_lock)
    monkeypatch.setattr(browser, "_select_port", lambda engine: 9222)
    monkeypatch.setattr(browser, "_host_for_engine", lambda engine=None: "browser-vm")
    monkeypatch.setattr(browser, "_cdp_ws", lambda port, host=None: "ws://browser-vm/devtools/browser/id")
    monkeypatch.setattr(
        browser,
        "_resolve_endpoint",
        lambda engine=None: SimpleNamespace(
            host="browser-vm", port=9222, source="ST_BROWSER_HOST", debug_local=False
        ),
    )
    monkeypatch.setattr(
        "cli.extensions.dispatch_extension",
        lambda record, owner_argv, *, context: captured.append(owner_argv) or 0,
    )
    code = browser.run_registered(object(), argv, _browser_context(tmp_path))
    assert captured and captured[0][0] == "--request"
    return code, json.loads(captured[0][1])


def test_browser_health_uses_owner_with_resolved_remote_target(tmp_path, monkeypatch) -> None:
    code, request = _registered_browser_request(monkeypatch, tmp_path, ["--proxmox", "health"])

    assert code == 0
    assert request["operation"] == "health"
    assert request["target"] == "proxmox"
    assert request["endpoint"] == {
        "host": "browser-vm",
        "port": 9222,
        "ws": "ws://browser-vm:9222",
        "source": "ST_BROWSER_HOST",
        "debug_local": False,
    }


def test_browser_health_defaults_to_local_ai_with_fixed_session(tmp_path, monkeypatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    code, request = _registered_browser_request(monkeypatch, tmp_path, ["health"])

    assert code == 0
    assert request["target"] == "local-ai"
    assert request["args"] == ["--session", "st-local-ai", "health"]
    assert request["launch"]["window_mode"] == "headless"
    assert request["launch"]["prefix"][-2:] == ["--args", _LOCAL_AI_HEADLESS_ARGS]


def test_browser_update_needs_only_agent_browser_bin(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cli.lib.browser_policy.system_chrome_path",
        lambda env=None: pytest.fail("update consulted Chrome launch policy"),
    )
    code, request = _registered_browser_request(monkeypatch, tmp_path, ["update"])

    assert code == 0
    assert request["operation"] == "update"
    assert request["args"] == ["update"]
    assert request["launch"] == {
        "agent_browser_bin": "/usr/bin/agent-browser",
        "prefix": [],
        "window_mode": "none",
        "default_launch": False,
        "minimize": False,
        "window_class": "",
    }


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
    assert browser.run_registered(object(), ["health", "--help"], {}) == 0


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
    output = "\n".join(["192.0.2.34", "172.24.0.1", "10.1.2.3"])

    assert browser._select_browser_vm_ip(output, {}) == "192.0.2.34"


def test_browser_vm_ip_selection_honors_prefix() -> None:
    output = "\n".join(["192.0.2.34", "10.1.2.3"])

    assert browser._select_browser_vm_ip(output, {"ST_BROWSER_VM_IP_PREFIX": "10."}) == "10.1.2.3"


def test_browser_url_resolves_project(capsys) -> None:
    route = SimpleNamespace(url="https://terminal.example.com/", project_id="a-term", source="hosts.browser_frontend")
    with patch("cli.commands.browser.resolve_browser_project_route", return_value=route):
        code = browser._browser_url(["terminal"])

    assert code == 0
    assert capsys.readouterr().out == "https://terminal.example.com/ # a-term hosts.browser_frontend\n"


def test_browser_endpoint_prints_canonical_http_url(capsys) -> None:
    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser-vm"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser-vm/devtools/browser/abc"),
    ):
        code = browser._browser_endpoint([], None)

    assert code == 0
    assert capsys.readouterr().out == "http://browser-vm:9222\n"


def test_browser_endpoint_prints_canonical_ws_url(capsys) -> None:
    with (
        patch("cli.commands.browser._select_port", return_value=9222),
        patch("cli.commands.browser._host_for_engine", return_value="browser-vm"),
        patch("cli.commands.browser._cdp_ws", return_value="ws://browser-vm/devtools/browser/abc"),
    ):
        code = browser._browser_endpoint(["--ws"], None)

    assert code == 0
    assert capsys.readouterr().out == "ws://browser-vm/devtools/browser/abc\n"


def _clear_local_ai_window_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AGENT_BROWSER_PROFILE",
        "AGENT_BROWSER_EXECUTABLE_PATH",
        "AGENT_BROWSER_HEADED",
        "AGENT_BROWSER_ARGS",
        "ST_BROWSER_LOCAL_AI_VISIBLE",
        "ST_BROWSER_LOCAL_AI_HEADLESS",
        "ST_BROWSER_LOCAL_AI_MINIMIZED",
    ):
        monkeypatch.delenv(name, raising=False)


_LOCAL_AI_MINIMIZED_ARGS = (
    "--class=st-browser-ai,--start-minimized,--disable-renderer-backgrounding,"
    "--disable-backgrounding-occluded-windows,--disable-background-timer-throttling,"
    "--disable-features=CalculateNativeWinOcclusion"
)
_LOCAL_AI_HEADLESS_ARGS = (
    "--enable-gpu,--use-angle=vulkan,--enable-features=Vulkan,"
    "--disable-vulkan-surface,--disable-software-rasterizer"
)


def test_browser_auto_open_normalizes_local_profile(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    monkeypatch.setattr(browser, "resolve_browser_location", lambda value: "http://app.lan:3005/")
    code, request = _registered_browser_request(monkeypatch, tmp_path, ["open", "portfolio-ai"])

    assert code == 0
    assert request["args"] == ["--session", "st-local-ai", "open", "http://app.lan:3005/"]
    assert request["launch"]["prefix"] == [
        "--profile",
        "AI",
        "--executable-path",
        "/usr/bin/google-chrome-stable",
        "--args",
        _LOCAL_AI_HEADLESS_ARGS,
    ]


def test_local_ai_agent_args_hardware_headless_is_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    with patch("cli.lib.browser_policy.system_chrome_path", return_value="/usr/bin/google-chrome-stable"):
        args = browser._local_ai_agent_args(["open", "http://app.lan/"])
    assert "--headed" not in args
    assert args[args.index("--args") + 1] == _LOCAL_AI_HEADLESS_ARGS
    flags = args[args.index("--args") + 1].split(",")
    assert "--use-angle=vulkan" in flags
    assert "--disable-vulkan-surface" in flags
    assert "--disable-software-rasterizer" in flags
    assert "--no-sandbox" not in flags


def test_local_ai_agent_args_minimized_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_MINIMIZED", "1")
    with patch("cli.lib.browser_policy.system_chrome_path", return_value="/usr/bin/google-chrome-stable"):
        args = browser._local_ai_agent_args(["open", "http://app.lan/"])
    assert "--headed" in args
    assert args[args.index("--args") + 1] == _LOCAL_AI_MINIMIZED_ARGS
    # No injected Chrome flag may contain a comma (agent-browser splits --args on commas).
    for flag in _LOCAL_AI_MINIMIZED_ARGS.split(","):
        assert flag.count(",") == 0 and flag.startswith("--")


def test_local_ai_screenshot_path_resolves_relative_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    args = browser._with_resolved_local_screenshot_path(
        ["screenshot", "nested/page.png"],
        "screenshot",
    )
    assert Path(args[1]).is_absolute()
    assert args[1] == str(tmp_path / "nested/page.png")
    assert (tmp_path / "nested").is_dir()


def test_local_ai_agent_args_visible_keeps_window_without_minimize_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_VISIBLE", "1")
    with patch("cli.lib.browser_policy.system_chrome_path", return_value="/usr/bin/google-chrome-stable"):
        args = browser._local_ai_agent_args(["open", "http://app.lan/"])
    assert "--headed" in args
    assert "--args" not in args


def test_local_ai_agent_args_headless_omits_headed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_HEADLESS", "1")
    with patch("cli.lib.browser_policy.system_chrome_path", return_value="/usr/bin/google-chrome-stable"):
        args = browser._local_ai_agent_args(["open", "http://app.lan/"])
    assert "--headed" not in args
    assert args[args.index("--args") + 1] == _LOCAL_AI_HEADLESS_ARGS


def test_local_ai_policy_uses_singleton_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    assert browser._with_local_ai_session(["snapshot"]) == ["--session", "st-local-ai", "snapshot"]


def test_local_ai_policy_blocks_additional_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    with (
        pytest.raises(typer.Exit) as raised,
    ):
        browser._with_local_ai_session(["--session", "parallel", "snapshot"])

    assert raised.value.exit_code == 75


def test_local_ai_browser_fails_fast_when_command_lock_is_busy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_local_ai_window_env(monkeypatch)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    @contextmanager
    def busy():
        yield False

    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/usr/bin/agent-browser")
    monkeypatch.setattr("cli.lib.browser_policy.system_chrome_path", lambda env=None: "/usr/bin/chrome")
    monkeypatch.setattr(browser, "_local_ai_command_lock", busy)
    with patch("cli.extensions.dispatch_extension") as dispatch:
        code = browser.run_registered(object(), ["snapshot"], _browser_context(tmp_path))

    assert code == 75
    dispatch.assert_not_called()


def test_explicit_visible_overrides_ambient_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    # A host-wide ST_BROWSER_LOCAL_AI_HEADLESS=1 default must not silently swallow
    # a deliberate per-command ST_BROWSER_LOCAL_AI_VISIBLE=1 request.
    _clear_local_ai_window_env(monkeypatch)
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_HEADLESS", "1")
    monkeypatch.setenv("ST_BROWSER_LOCAL_AI_VISIBLE", "1")
    assert browser._local_ai_window_mode() == "visible"
    with patch("cli.lib.browser_policy.system_chrome_path", return_value="/usr/bin/google-chrome-stable"):
        args = browser._local_ai_agent_args(["open", "http://app.lan/"])
    assert "--headed" in args


def test_local_ai_agent_args_respects_user_supplied_args(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_local_ai_window_env(monkeypatch)
    with patch("cli.lib.browser_policy.system_chrome_path", return_value="/usr/bin/google-chrome-stable"):
        args = browser._local_ai_agent_args(["--args", "--no-sandbox", "open", "http://app.lan/"])
    assert args.count("--args") == 1
    assert _LOCAL_AI_MINIMIZED_ARGS not in args
    assert _LOCAL_AI_HEADLESS_ARGS not in args


def test_browser_force_proxmox_normalizes_remote_request(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_SESSION", raising=False)
    monkeypatch.delenv("ST_BROWSER_SESSION", raising=False)
    monkeypatch.setattr(browser, "_default_browser_session", lambda: "st-repo-1234")
    code, request = _registered_browser_request(
        monkeypatch, tmp_path, ["--proxmox", "open", "https://example.com"]
    )

    assert code == 0
    assert request["target"] == "proxmox"
    assert request["args"] == ["--session", "st-repo-1234", "open", "https://example.com"]
    assert request["default_viewport"] == {"width": "1600", "height": "900"}
    assert request["endpoint"]["ws"] == "ws://browser-vm/devtools/browser/id"


def test_browser_select_port_honors_explicit_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ST_BROWSER_HOST", "192.0.2.10")
    monkeypatch.setenv("ST_BROWSER_PORT", "9333")

    with patch("cli.commands.browser._engine_up", return_value=True) as engine_up:
        assert browser._select_port("chrome") == 9333

    engine_up.assert_called_once_with(9333, host="192.0.2.10")


def test_browser_open_uses_repo_scoped_session(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_SESSION", raising=False)
    monkeypatch.delenv("ST_BROWSER_SESSION", raising=False)

    monkeypatch.setattr(browser, "_default_browser_session", lambda: "st-repo-1234")
    _, request = _registered_browser_request(
        monkeypatch, tmp_path, ["--proxmox", "open", "https://example.com"]
    )

    assert request["args"][:2] == ["--session", "st-repo-1234"]


def test_browser_open_blocks_loopback_url_before_selecting_browser(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ST_BROWSER_CONFIRM_LOCAL_URL", raising=False)

    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/usr/bin/agent-browser")
    with patch("cli.commands.browser._select_port") as select_port, pytest.raises(typer.Exit) as raised:
        browser.run_registered(
            object(), ["--proxmox", "open", "http://127.0.0.1:3000/money"], _browser_context(tmp_path)
        )

    assert raised.value.exit_code == 2
    select_port.assert_not_called()


def test_browser_open_resolves_project_target(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_SESSION", raising=False)
    monkeypatch.delenv("ST_BROWSER_SESSION", raising=False)

    monkeypatch.setattr(browser, "_default_browser_session", lambda: "st-repo-1234")
    monkeypatch.setattr(browser, "_resolve_guarded_browser_location", lambda value: "https://terminal.example.com/")
    _, request = _registered_browser_request(monkeypatch, tmp_path, ["--proxmox", "open", "a-term"])

    assert request["args"][-2:] == ["open", "https://terminal.example.com/"]


def test_browser_open_preserves_explicit_session(tmp_path, monkeypatch) -> None:
    _, request = _registered_browser_request(
        monkeypatch,
        tmp_path,
        ["--proxmox", "--session", "operator", "open", "https://example.com"],
    )

    assert request["args"][:2] == ["--session", "operator"]


def test_browser_check_blocks_localhost_url_before_selecting_browser(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ST_BROWSER_CONFIRM_LOCAL_URL", raising=False)

    monkeypatch.setattr(browser, "_agent_browser_bin", lambda: "/usr/bin/agent-browser")
    with patch("cli.commands.browser._select_port") as select_port, pytest.raises(typer.Exit) as raised:
        browser.run_registered(
            object(),
            ["--proxmox", "check", "http://localhost:3000/money", "/tmp/check.png"],
            _browser_context(tmp_path),
        )

    assert raised.value.exit_code == 2
    select_port.assert_not_called()


def test_browser_local_url_confirmation_token_allows_intentional_target(monkeypatch) -> None:
    target = "http://localhost:3000/money?token=secret"
    message = browser._local_browser_url_error(target)

    assert message is not None
    assert "target=localhost:3000" in message
    assert "token=secret" not in message

    monkeypatch.setenv("ST_BROWSER_CONFIRM_LOCAL_URL", browser._local_url_confirmation_token(target))

    assert browser._local_browser_url_error(target) is None


def test_browser_check_normalizes_responsive_evidence_request(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ST_BROWSER_CHECK_SETTLE_MS", "750")
    _, request = _registered_browser_request(
        monkeypatch,
        tmp_path,
        ["--proxmox", "check", "--session", "operator", "https://example.com", "/tmp/check.png"],
    )

    assert request["operation"] == "check"
    assert request["check"]["session"] == "operator"
    assert request["check"]["settle_ms"] == "750"
    assert [(row["label"], row["width"], row["height"]) for row in request["check"]["viewports"]] == [
        ("desktop", 1600, 900),
        ("narrow", 1180, 900),
        ("mobile", 390, 844),
    ]
    assert request["check"]["viewports"][2]["path"] == "/tmp/check-mobile.png"


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


@pytest.mark.parametrize("arguments", [
    ["search", "--query", "SummitFlow", "--limit", "1"],
    ["fetch", "--url", "https://example.com", "--backend", "jina", "--max-chars", "500"],
    ["research", "--query", "SummitFlow", "--backend", "direct"],
    ["benchmark", "--iterations", "99", "--max-chars", "100000"],
])
def test_web_uses_registered_public_executable(arguments, tmp_path) -> None:
    # Product normalization belongs to Agent Hub; ST preserves argv and presentation.
    from pathlib import Path

    with (
        patch("cli.extensions._resolve_executable", return_value=(Path("/trusted/web-research"), 0, "")),
        patch("cli.extensions.extension_context", return_value={"cwd": str(tmp_path)}),
        patch("cli.extensions._run_process", return_value=(0, '{"ok":true}\n', "")) as run_web,
        patch("cli.extension_presentation.current_root", return_value=tmp_path),
    ):
        result = runner.invoke(main_app, ["web", *arguments])

    assert result.exit_code == 0, result.output
    assert run_web.call_args.args[0] == ["/trusted/web-research", *arguments, "--compact"]
    assert result.output.startswith(f"WEB:{arguments[0]}:OK:0|details:")
    assert run_web.call_args.kwargs["capture"] is True


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


def test_proxmox_destroy_sends_purge_as_query_param() -> None:
    config = ProxmoxConfig(
        host="https://proxmox.example.test",
        token_id="user@pam!token",
        token_secret="secret",
        node="node1",
    )

    class Response:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, str]:
            return {"data": "UPID:test"}

    with (
        patch("cli.lib.proxmox.httpx.request", return_value=Response()) as request,
        patch("cli.lib.proxmox.time.sleep"),
    ):
        ProxmoxClient(config).destroy("101")

    assert request.call_args_list[-1].args[:2] == (
        "DELETE",
        "https://proxmox.example.test/api2/json/nodes/node1/qemu/101?purge=1",
    )
    assert request.call_args_list[-1].kwargs["data"] is None


def test_setup_services_dry_run_does_not_mutate() -> None:
    with patch("cli.commands.setup._link_st") as link_st:
        result = runner.invoke(setup.app, ["services", "--dry-run"])

    assert result.exit_code == 0
    assert "SETUP SERVICES" in result.output
    link_st.assert_not_called()


@pytest.mark.parametrize("failed_step", ["sync_backend", "build_frontend", "run_migrations"])
def test_rebuild_failure_never_restarts_services(failed_step):
    with (
        patch("cli.commands.service._load", return_value=_project()),
        patch.object(service_ops, "ensure_infra", return_value=0),
        patch.object(service_ops, "sync_backend", return_value=int(failed_step == "sync_backend")),
        patch.object(service_ops, "build_frontend", return_value=int(failed_step == "build_frontend")),
        patch.object(service_ops, "run_migrations", return_value=int(failed_step == "run_migrations")),
        patch.object(service_ops, "restart_service") as restart,
        patch.object(service_ops, "sync_systemd_units") as sync,
    ):
        result = runner.invoke(service.app, ["rebuild", "summitflow"])
    assert result.exit_code == 1
    restart.assert_not_called()
    sync.assert_not_called()


def test_backend_sync_uses_lockfile(tmp_path):
    from dataclasses import replace
    project = replace(_project(), backend_dir=tmp_path)
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "uv.lock").touch()
    with patch.object(service_ops, "run", return_value=0) as run:
        assert service_ops.sync_backend(project) == 0
    run.assert_called_once_with(["uv", "sync", "--locked"], cwd=tmp_path, quiet_success=True)


def test_systemd_bus_discovery_uses_existing_owned_socket(tmp_path, monkeypatch):
    import socket
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    with socket.socket(socket.AF_UNIX) as bus:
        bus.bind(str(tmp_path / "bus"))
        env = service_ops._command_env(["systemctl", "--user", "is-active", "example.service"])
    assert env is not None
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={tmp_path}/bus"
    assert service_ops._command_env(["pnpm", "build"]) is None


def test_rebuild_fails_when_restarted_worker_is_not_active():
    with (
        patch("cli.commands.service._load", return_value=_project()),
        patch.object(service_ops, "ensure_infra", return_value=0),
        patch.object(service_ops, "sync_backend", return_value=0),
        patch.object(service_ops, "build_frontend", return_value=0),
        patch.object(service_ops, "run_migrations", return_value=0),
        patch.object(service_ops, "sync_systemd_units", return_value=0),
        patch.object(service_ops, "restart_service", return_value=0),
        patch.object(service_ops, "verify_health", return_value=0),
        patch.object(service_ops, "service_state", return_value="failed"),
        patch.object(service_ops, "sync_seeds") as seeds,
    ):
        result = runner.invoke(service.app, ["rebuild", "summitflow"])
    assert result.exit_code == 1
    assert "worker summitflow-worker.service: failed" in result.output
    seeds.assert_not_called()


def test_backend_sync_keeps_declared_quality_gate_dependencies(tmp_path):
    from dataclasses import replace
    project = replace(_project(), backend_dir=tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project.optional-dependencies]\ndev = ["pytest"]\n')
    (tmp_path / "uv.lock").touch()
    with patch.object(service_ops, "run", return_value=0) as run:
        assert service_ops.sync_backend(project) == 0
    run.assert_called_once_with(["uv", "sync", "--locked", "--extra", "dev"], cwd=tmp_path, quiet_success=True)
