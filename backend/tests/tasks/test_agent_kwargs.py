"""Tests for Agent Hub completion kwargs used by autonomous execution."""

from __future__ import annotations

from unittest.mock import patch

from app.tasks.autonomous.exec_modules._agent_kwargs import build_complete_kwargs


def test_build_complete_kwargs_passes_task_id_as_external_id() -> None:
    """Autocode sessions should link back to the owning task explicitly."""
    with patch(
        "app.tasks.autonomous.exec_modules._agent_kwargs._detect_git_branch",
        return_value="task-123/main",
    ):
        result = build_complete_kwargs(
            prompt="Refactor this file",
            agent_slug="refactor",
            project_path="/tmp/worktree",
            project_id="summitflow",
            task_id="task-123",
            session_id="sess-1",
            max_turns=25,
        )

    assert result["external_id"] == "task-123"
    assert result["current_branch"] == "task-123/main"
    assert result["working_dir"] == "/tmp/worktree"


def test_build_complete_kwargs_does_not_forward_project_tier_preference() -> None:
    """Autocode should respect the selected specialist agent's primary model."""
    with patch(
        "app.tasks.autonomous.exec_modules._agent_kwargs._detect_git_branch",
        return_value="task-123/main",
    ):
        result = build_complete_kwargs(
            prompt="Refactor this file",
            agent_slug="refactor",
            project_path="/tmp/worktree",
            project_id="agent-hub",
            task_id="task-123",
            session_id="sess-1",
            max_turns=25,
            model_override=None,
        )

    assert "tier_preference" not in result
