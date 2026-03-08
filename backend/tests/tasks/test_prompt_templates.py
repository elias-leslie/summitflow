"""Tests for autonomous prompt template fallback behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

_PROMPTS = "app.tasks.autonomous.exec_modules.prompts"


class TestPromptTemplateFallbacks:
    @patch(f"{_PROMPTS}.logger")
    @patch(f"{_PROMPTS}.get_prompt_template")
    def test_build_fix_prompt_uses_transient_fallback_template(
        self,
        mock_get_prompt_template: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules._prompt_fetch import TransientPromptFetchError
        from app.tasks.autonomous.exec_modules.prompts import build_fix_prompt

        mock_get_prompt_template.side_effect = TransientPromptFetchError("connection refused")

        prompt = build_fix_prompt(
            subtask={
                "subtask_id": "1.1",
                "description": "Refactor the activity timeline",
                "steps_from_table": [{"step_number": 1, "description": "Preserve behavior"}],
            },
            failed_steps=[{"step_number": 1, "reason": "TypeScript error"}],
            previous_response="irrelevant",
        )

        assert "Refactor the activity timeline" in prompt
        assert "TypeScript error" in prompt
        assert "Preserve behavior" in prompt
        mock_logger.warning.assert_called_once()

    @patch(f"{_PROMPTS}.get_prompt_template")
    def test_build_fix_prompt_raises_for_non_transient_prompt_failure(
        self,
        mock_get_prompt_template: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules._prompt_fetch import PromptFetchError
        from app.tasks.autonomous.exec_modules.prompts import build_fix_prompt

        mock_get_prompt_template.side_effect = PromptFetchError("prompt missing")

        with pytest.raises(PromptFetchError, match="prompt missing"):
            build_fix_prompt(
                subtask={
                    "subtask_id": "1.1",
                    "description": "Refactor the activity timeline",
                    "steps_from_table": [],
                },
                failed_steps=[{"step_number": 1, "reason": "TypeScript error"}],
                previous_response="irrelevant",
            )

    @patch(f"{_PROMPTS}.build_health_context", return_value="")
    @patch(f"{_PROMPTS}.build_resume_context", return_value="")
    @patch(f"{_PROMPTS}.get_handoff_context", return_value={})
    @patch(f"{_PROMPTS}.get_task_spirit")
    @patch(f"{_PROMPTS}.logger")
    @patch(f"{_PROMPTS}.get_prompt_template")
    def test_build_subtask_prompt_uses_transient_fallback_template(
        self,
        mock_get_prompt_template: MagicMock,
        mock_logger: MagicMock,
        mock_get_task_spirit: MagicMock,
        _mock_handoff: MagicMock,
        _mock_resume: MagicMock,
        _mock_health: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules._prompt_fetch import TransientPromptFetchError
        from app.tasks.autonomous.exec_modules.prompts import build_subtask_prompt

        mock_get_prompt_template.side_effect = TransientPromptFetchError("connection refused")
        mock_get_task_spirit.return_value = {
            "objective": "Reduce the component size while preserving behavior",
            "spirit_anti": "- Do not change UI behavior",
        }

        prompt = build_subtask_prompt(
            task_id="task-1",
            subtask={
                "subtask_id": "1.1",
                "description": "Extract reusable ActivityTimeline helpers",
                "steps_from_table": [{"step_number": 1, "description": "Keep output stable"}],
            },
            project_id="agent-hub",
            project_path="/tmp/worktree",
        )

        assert "Reduce the component size while preserving behavior" in prompt
        assert "Do not change UI behavior" in prompt
        assert "Extract reusable ActivityTimeline helpers" in prompt
        assert "/tmp/worktree" in prompt
        mock_logger.warning.assert_called_once()
