from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.tasks.autonomous.exec_modules import subtask_executor


def test_run_initial_agent_fails_interrupted_completion_without_quality_pass() -> None:
    response = SimpleNamespace(
        content="Session interrupted: Repeated identical tool result 5 times for bash",
        finish_reason="error",
    )

    with (
        patch(
            "app.tasks.autonomous.exec_modules.subtask_executor.execute_agent_initial",
            return_value=(response, "sess-123"),
        ),
        patch("app.tasks.autonomous.exec_modules.subtask_executor.run_self_healing_loop") as heal_loop,
    ):
        result = subtask_executor._run_initial_agent(
            task_id="task-123",
            subtask_id="subtask-db-id",
            subtask_short_id="1.1",
            subtask={"steps": [{"description": "Verify work"}]},
            agent_slug="debugger",
            prompt="Do the work",
            project_path="/tmp/project",
            project_id="summitflow",
        )

    all_passed, step_results, self_fix, supervisor_fix, extensions, content, session_id = result
    assert all_passed is False
    assert step_results[0]["reason"] == "agent_interrupted"
    assert "Repeated identical tool result" in step_results[0]["output"]
    assert self_fix == 0
    assert supervisor_fix == 0
    assert extensions == 0
    assert content == response.content
    assert session_id == "sess-123"
    heal_loop.assert_not_called()
