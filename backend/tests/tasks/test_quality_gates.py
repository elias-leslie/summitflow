"""Tests for autonomous closeout quality gates."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.quality_gates import (
    _run_gate_subprocess,
    build_final_quality_gate_command,
    run_final_quality_gate,
)


def test_final_quality_gate_command_scopes_configured_aggregate_check() -> None:
    with patch(
        "app.tasks.autonomous.exec_modules.quality_gates.build_st_check_command",
        return_value=["st", "check", "--quick"],
    ):
        assert build_final_quality_gate_command("st", "summitflow") == [
            "st",
            "-P",
            "summitflow",
            "check",
            "--quick",
            "--changed-only",
        ]


def test_final_quality_gate_command_preserves_explicit_tool_config() -> None:
    with patch(
        "app.tasks.autonomous.exec_modules.quality_gates.build_st_check_command",
        return_value=["st", "check", "ruff"],
    ):
        assert build_final_quality_gate_command("st", "summitflow") == [
            "st",
            "-P",
            "summitflow",
            "check",
            "ruff",
        ]


@patch("app.tasks.autonomous.exec_modules.quality_gates._run_gate_subprocess")
@patch("app.tasks.autonomous.exec_modules.quality_gates._emit_gate_start")
@patch("app.tasks.autonomous.exec_modules.quality_gates.find_check_tool")
def test_run_final_quality_gate_uses_configured_closeout(
    mock_find: MagicMock,
    _mock_emit: MagicMock,
    mock_run: MagicMock,
) -> None:
    mock_find.return_value = "st"
    mock_run.return_value = True

    with patch(
        "app.tasks.autonomous.exec_modules.quality_gates.build_st_check_command",
        return_value=["st", "check", "--quick"],
    ):
        assert run_final_quality_gate("task-1", "/workspace/project", "summitflow") is True

    mock_run.assert_called_once_with(
        "task-1",
        ["st", "-P", "summitflow", "check", "--quick", "--changed-only"],
        "/workspace/project",
        "summitflow",
    )


@patch("app.tasks.autonomous.exec_modules.quality_gates.emit_log")
@patch("app.tasks.autonomous.exec_modules.quality_gates._task_changed_files")
@patch("app.tasks.autonomous.exec_modules.quality_gates.subprocess.run")
def test_run_gate_subprocess_passes_committed_task_file_scope(
    mock_run: MagicMock,
    mock_changed_files: MagicMock,
    _mock_emit_log: MagicMock,
) -> None:
    mock_changed_files.return_value = ["frontend/app/example.tsx"]
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""

    assert _run_gate_subprocess(
        "task-1",
        ["st", "-P", "summitflow", "check", "--quick", "--changed-only"],
        "/workspace/project",
        "summitflow",
    )

    assert (
        mock_run.call_args.kwargs["env"]["ST_CHECK_CHANGED_FILES"]
        == "frontend/app/example.tsx"
    )
