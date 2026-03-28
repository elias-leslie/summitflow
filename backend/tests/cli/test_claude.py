"""Tests for the Claude worker CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.claude import WorkerDispatch, app

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

        result = runner.invoke(app, ["task", "task-abc", "--timeout-seconds", "900"])

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

        result = runner.invoke(app, ["task", "task-xyz", "--feedback-file", str(feedback_file)])

    assert result.exit_code == 0
    command = mock_run.call_args.args[0]
    assert "--feedback-text" in command
    assert "Tighten the extraction and keep constants grouped." in command


def test_claude_task_passes_effort_skills_and_system_prompt(tmp_path: Path) -> None:
    agent_hub_root = _prepare_agent_hub_root(tmp_path)
    project_root = tmp_path / "target-project"
    project_root.mkdir()

    with (
        patch("cli.commands.claude.STClient") as mock_client_cls,
        patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "vantage", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(agent_hub_root)},
            ],
        ),
        patch("cli.commands.claude.subprocess.run") as mock_run,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.get_task.return_value = {"id": "task-ui", "project_id": "vantage"}
        mock_client.validate_ready.return_value = {"ready": True}
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        result = runner.invoke(
            app,
            [
                "task",
                "task-ui",
                "--model",
                "claude-opus-4-6",
                "--effort",
                "max",
                "--append-system-prompt",
                "Use /frontend-design before editing.",
                "--skill",
                "frontend-design",
            ],
        )

    assert result.exit_code == 0
    command = mock_run.call_args.args[0]
    assert "--effort" in command
    assert "max" in command
    assert "--append-system-prompt" in command
    assert "Use /frontend-design before editing." in command
    assert "--skill" in command
    assert "frontend-design" in command


def test_claude_task_blocks_unready_task(tmp_path: Path) -> None:
    with patch("cli.commands.claude.STClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.get_task.return_value = {"id": "task-abc", "project_id": "summitflow"}
        mock_client.validate_ready.return_value = {
            "ready": False,
            "issues": ["missing done_when"],
            "suggestions": ["Run st context task-abc and fill task spirit"],
        }

        result = runner.invoke(app, ["task", "task-abc"])

    assert result.exit_code == 1
    assert "not execution-ready" in result.output
    assert "missing done_when" in result.output


def test_claude_task_help_mentions_feedback_options() -> None:
    result = runner.invoke(app, ["task", "--help"])

    assert result.exit_code == 0
    assert "--feedback-text" in result.output
    assert "--feedback-file" in result.output
    assert "7200" in result.output


def test_claude_task_prints_patience_note(tmp_path: Path) -> None:
    agent_hub_root = _prepare_agent_hub_root(tmp_path)
    project_root = tmp_path / "target-project"
    project_root.mkdir()

    with (
        patch("cli.commands.claude.STClient") as mock_client_cls,
        patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "vantage", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(agent_hub_root)},
            ],
        ),
        patch("cli.commands.claude.subprocess.run") as mock_run,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.get_task.return_value = {"id": "task-ui", "project_id": "vantage"}
        mock_client.validate_ready.return_value = {"ready": True}
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        result = runner.invoke(app, ["task", "task-ui"])

    assert result.exit_code == 0
    assert "Do not redrive early" in result.output


def test_claude_batch_runs_multiple_tasks_and_optional_closeout() -> None:
    dispatches = [
        WorkerDispatch(
            index=0,
            task_id="task-a",
            project_id="summitflow",
            project_root=Path("/tmp/project-a"),
            command=["worker-a"],
            cwd=Path("/tmp/agent-hub/backend"),
        ),
        WorkerDispatch(
            index=1,
            task_id="task-b",
            project_id="agent-hub",
            project_root=Path("/tmp/project-b"),
            command=["worker-b"],
            cwd=Path("/tmp/agent-hub/backend"),
        ),
    ]

    with (
        patch("cli.commands.claude._prepare_worker_dispatch", side_effect=dispatches) as mock_prepare,
        patch("cli.commands.claude._run_batch_workers", return_value=[(dispatches[0], 0), (dispatches[1], 0)]),
        patch("cli.commands.claude._commit_and_done_task", return_value=0) as mock_closeout,
    ):
        result = runner.invoke(
            app,
            [
                "batch",
                "task-a",
                "task-b",
                "--max-subagents",
                "2",
                "--commit-and-done",
            ],
        )

    assert result.exit_code == 0
    assert mock_prepare.call_count == 2
    assert mock_closeout.call_count == 2
    assert "Committed and closed task-a" in result.output
    assert "Committed and closed task-b" in result.output


def test_claude_batch_help_mentions_batch_flags() -> None:
    result = runner.invoke(app, ["batch", "--help"])

    assert result.exit_code == 0
    assert "--max-subagents" in result.output
    assert "--commit-and-done" in result.output


def test_claude_orchestrator_invokes_single_worker_with_prompt_and_agents(tmp_path: Path) -> None:
    agent_hub_root = _prepare_agent_hub_root(tmp_path)
    project_root = tmp_path / "target-project"
    worktree_a = tmp_path / "lanes" / "task-a"
    worktree_b = tmp_path / "lanes" / "task-b"
    project_root.mkdir()
    worktree_a.mkdir(parents=True)
    worktree_b.mkdir(parents=True)

    with (
        patch("cli.commands.claude.STClient") as mock_client_cls,
        patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "agent-hub", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(agent_hub_root)},
            ],
        ),
        patch(
            "cli.commands.claude._run_text_command",
            side_effect=[
                "TASK:task-a|pending|P3|refactor|SIMPLE\nCONTEXT:modify:backend/a.py\n",
                "TASK:task-b|pending|P3|refactor|SIMPLE\nCONTEXT:modify:backend/b.py\n",
            ],
        ),
        patch("cli.commands.claude.subprocess.run") as mock_run,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.get_task.side_effect = [
            {
                "id": "task-a",
                "project_id": "agent-hub",
                "worktree": {"path": str(worktree_a), "branch": "task-a/main", "is_active": True},
            },
            {
                "id": "task-b",
                "project_id": "agent-hub",
                "worktree": {"path": str(worktree_b), "branch": "task-b/main", "is_active": True},
            },
        ]
        mock_client.validate_ready.return_value = {"ready": True}
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        result = runner.invoke(
            app,
            ["orchestrator", "task-a", "task-b", "--max-subagents", "2"],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()
    command = mock_run.call_args.args[0]
    assert "--prompt-file" in command
    assert "--agents-file" in command
    assert "--source" in command
    assert "st-cli-orchestrator" in command
    assert "--allowed-tools" in command
    assert "Read,Agent,Edit,MultiEdit,Write,Bash,Glob,Grep,LS" in command
    assert command.count("--batch-task-id") == 2
    assert "task-a" in command
    assert "task-b" in command


def test_claude_orchestrator_blocks_mixed_projects(tmp_path: Path) -> None:
    with patch("cli.commands.claude.STClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.get_task.side_effect = [
            {"id": "task-a", "project_id": "agent-hub", "worktree": {"path": "/tmp/a", "branch": "task-a/main", "is_active": True}},
            {"id": "task-b", "project_id": "summitflow", "worktree": {"path": "/tmp/b", "branch": "task-b/main", "is_active": True}},
        ]
        mock_client.validate_ready.return_value = {"ready": True}

        with patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "agent-hub", "root_path": "/tmp/agent-hub"},
                {"id": "summitflow", "root_path": "/tmp/summitflow"},
            ],
        ), patch("cli.commands.claude._run_text_command", return_value="TASK:task-a|pending|P3|refactor|SIMPLE\n"):
            result = runner.invoke(app, ["orchestrator", "task-a", "task-b"])

    assert result.exit_code == 1
    assert "same project" in result.output


def test_claude_orchestrator_claims_missing_lane_before_dispatch(tmp_path: Path) -> None:
    agent_hub_root = _prepare_agent_hub_root(tmp_path)
    project_root = tmp_path / "target-project"
    worktree = tmp_path / "lanes" / "task-a"
    project_root.mkdir()
    worktree.mkdir(parents=True)

    with (
        patch("cli.commands.claude.STClient") as mock_client_cls,
        patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "agent-hub", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(agent_hub_root)},
            ],
        ),
        patch("cli.commands.claude._run_text_command") as mock_text_command,
        patch("cli.commands.claude.subprocess.run") as mock_run,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.get_task.side_effect = [
            {"id": "task-a", "project_id": "agent-hub"},
            {
                "id": "task-a",
                "project_id": "agent-hub",
                "worktree": {"path": str(worktree), "branch": "task-a/main", "is_active": True},
            },
        ]
        mock_client.validate_ready.return_value = {"ready": True}
        mock_text_command.side_effect = [
            "CLAIMED task-a\n",
            "TASK:task-a|pending|P3|refactor|SIMPLE\nCONTEXT:modify:backend/a.py\n",
        ]
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        result = runner.invoke(app, ["orchestrator", "task-a"])

    assert result.exit_code == 0
    assert mock_text_command.call_args_list[0].kwargs["command"] == ["st", "claim", "task-a"]
    assert mock_text_command.call_args_list[1].kwargs["command"] == ["st", "context", "task-a"]


def test_claude_orchestrator_accepts_running_task_with_active_worktree(tmp_path: Path) -> None:
    agent_hub_root = _prepare_agent_hub_root(tmp_path)
    project_root = tmp_path / "target-project"
    worktree = tmp_path / "lanes" / "task-a"
    project_root.mkdir()
    worktree.mkdir(parents=True)

    with (
        patch("cli.commands.claude.STClient") as mock_client_cls,
        patch(
            "cli.commands.claude.projects_api",
            side_effect=[
                {"id": "agent-hub", "root_path": str(project_root)},
                {"id": "agent-hub", "root_path": str(agent_hub_root)},
            ],
        ),
        patch(
            "cli.commands.claude._run_text_command",
            return_value=(
                "TASK:task-a|running|P3|refactor|SIMPLE\n"
                f"WORKTREE_PATH:{worktree}\n"
            ),
        ) as mock_text_command,
        patch("cli.commands.claude.subprocess.run") as mock_run,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.get_task.return_value = {
            "id": "task-a",
            "project_id": "agent-hub",
            "status": "running",
        }
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        result = runner.invoke(app, ["orchestrator", "task-a"])

    assert result.exit_code == 0
    mock_client.validate_ready.assert_not_called()
    assert [call.kwargs["command"] for call in mock_text_command.call_args_list] == [["st", "context", "task-a"]]


def test_claude_orchestrator_help_mentions_subagent_flag() -> None:
    result = runner.invoke(app, ["orchestrator", "--help"])

    assert result.exit_code == 0
    assert "--max-subagents" in result.output
