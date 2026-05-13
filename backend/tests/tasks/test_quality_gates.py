"""Tests for autonomous closeout quality gates."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.quality_gates import (
    build_final_quality_gate_command,
    run_final_quality_gate,
)


def test_final_quality_gate_command_is_project_scoped_and_changed_only() -> None:
    assert build_final_quality_gate_command("st", "summitflow") == [
        "st",
        "-P",
        "summitflow",
        "check",
        "--quick",
        "--changed-only",
    ]


@patch("app.tasks.autonomous.exec_modules.quality_gates._run_gate_subprocess")
@patch("app.tasks.autonomous.exec_modules.quality_gates._emit_gate_start")
@patch("app.tasks.autonomous.exec_modules.quality_gates.find_check_tool")
def test_run_final_quality_gate_uses_changed_only_closeout(
    mock_find: MagicMock,
    _mock_emit: MagicMock,
    mock_run: MagicMock,
) -> None:
    mock_find.return_value = "st"
    mock_run.return_value = True

    assert run_final_quality_gate("task-1", "/workspace/project", "summitflow") is True

    mock_run.assert_called_once_with(
        "task-1",
        ["st", "-P", "summitflow", "check", "--quick", "--changed-only"],
        "/workspace/project",
        "summitflow",
    )
