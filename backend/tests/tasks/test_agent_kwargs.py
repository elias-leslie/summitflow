"""Tests for Agent Hub completion kwargs used by autonomous execution."""

from __future__ import annotations

from unittest.mock import patch

from app.tasks.autonomous.exec_modules._agent_kwargs import (
    AUTONOMOUS_TURN_TIMEOUT_SECONDS,
    build_complete_kwargs,
)


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


def test_build_complete_kwargs_leaves_model_selection_to_agent_routing() -> None:
    """Autocode should defer normal model selection to the selected specialist agent."""
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


def test_build_complete_kwargs_sets_explicit_turn_timeout_for_autonomous_runs() -> None:
    """Autocode should give multi-turn specialist sessions a scaled HTTP ceiling."""
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
            max_turns=50,
        )

    assert result["timeout_seconds"] == AUTONOMOUS_TURN_TIMEOUT_SECONDS
