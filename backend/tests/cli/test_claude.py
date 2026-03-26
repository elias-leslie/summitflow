"""Tests for the Claude worker CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.claude import app

runner = CliRunner()


def _prepare_agent_hub_root(tmp_path: Path) -> Path:
    root = tmp_path / "agent-hub"
    python_bin = root / "backend" / ".venv" / "bin" / "python"
    script_path = root / "backend" / "scripts" / "run_claude_orchestrated_worker.py"
    python_bin.parent.mkdir(parents=True)
    script_path.parent.mkdir(parents=True)
    python_bin.write_text("#!/usr/bin/env python\n")
    script_path.write_text("print('ok')\n")
    return root


def test_claude_task_invokes_worker_with_resolved_roots(tmp_path: Path) -> None:
    agent_hub_root = _prepare_agent_hub_root(tmp_path)
    project_root = tmp_path / "target-project"
    project_root.mkdir()

    with (
        patch("cli.commands.claude.STClient") as mock_client_cls,
        patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "summitflow", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(agent_hub_root)},
            ],
        ),
        patch("cli.commands.claude.subprocess.run") as mock_run,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.get_task.return_value = {"id": "task-abc", "project_id": "summitflow"}
        mock_client.validate_ready.return_value = {"ready": True}
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        result = runner.invoke(app, ["task-abc", "--timeout-seconds", "900"])

    assert result.exit_code == 0
    mock_run.assert_called_once()
    command = mock_run.call_args.args[0]
    assert command[:2] == [
        str(agent_hub_root / "backend" / ".venv" / "bin" / "python"),
        str(agent_hub_root / "backend" / "scripts" / "run_claude_orchestrated_worker.py"),
    ]
    assert "--project-id" in command
    assert "--task-id" in command
    assert "--task-root" in command
    assert "--claim-if-needed" in command
    assert mock_run.call_args.kwargs["cwd"] == agent_hub_root / "backend"
    assert mock_run.call_args.kwargs["env"]["PYTHONPATH"] == "backend"


def test_claude_task_passes_feedback_file_contents(tmp_path: Path) -> None:
    agent_hub_root = _prepare_agent_hub_root(tmp_path)
    project_root = tmp_path / "target-project"
    project_root.mkdir()
    feedback_file = tmp_path / "feedback.txt"
    feedback_file.write_text("Tighten the extraction and keep constants grouped.\n")

    with (
        patch("cli.commands.claude.STClient") as mock_client_cls,
        patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "agent-hub", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(agent_hub_root)},
            ],
        ),
        patch("cli.commands.claude.subprocess.run") as mock_run,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.get_task.return_value = {"id": "task-xyz", "project_id": "agent-hub"}
        mock_client.validate_ready.return_value = {"ready": True}
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        result = runner.invoke(app, ["task-xyz", "--feedback-file", str(feedback_file)])

    assert result.exit_code == 0
    command = mock_run.call_args.args[0]
    assert "--feedback-text" in command
    assert "Tighten the extraction and keep constants grouped." in command


def test_claude_task_blocks_unready_task(tmp_path: Path) -> None:
    with patch("cli.commands.claude.STClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.get_task.return_value = {"id": "task-abc", "project_id": "summitflow"}
        mock_client.validate_ready.return_value = {
            "ready": False,
            "issues": ["missing done_when"],
            "suggestions": ["Run st context task-abc and fill task spirit"],
        }

        result = runner.invoke(app, ["task-abc"])

    assert result.exit_code == 1
    assert "not execution-ready" in result.output
    assert "missing done_when" in result.output


def test_claude_task_help_mentions_feedback_options() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--feedback-text" in result.output
    assert "--feedback-file" in result.output
