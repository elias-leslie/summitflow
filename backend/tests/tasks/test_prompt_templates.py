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
    @patch(f"{_PROMPTS}.build_conflict_context", return_value="")
    @patch(f"{_PROMPTS}.build_resume_context", return_value="")
    @patch(f"{_PROMPTS}._build_precision_code_search_block", return_value="\n# Precision Code Search\nPrecision Code Search: symbol-first")
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
        _mock_precision: MagicMock,
        _mock_resume: MagicMock,
        _mock_conflict: MagicMock,
        _mock_health: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules._prompt_fetch import TransientPromptFetchError
        from app.tasks.autonomous.exec_modules.prompts import build_subtask_prompt

        mock_get_prompt_template.side_effect = TransientPromptFetchError("connection refused")
        mock_get_task_spirit.return_value = {
            "objective": "Reduce the component size while preserving behavior",
            "spirit_anti": "- Do not change UI behavior",
            "done_when": ["No regressions", "Keep render output stable"],
            "context": {
                "files_to_modify": ["frontend/components/ActivityTimeline.tsx"],
                "files_to_create": ["frontend/components/ActivityTimelineParts.tsx"],
            },
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
        assert "Completion Criteria" in prompt
        assert "No regressions" in prompt
        assert "Expected Scope" in prompt
        assert "frontend/components/ActivityTimeline.tsx" in prompt
        assert "Extract reusable ActivityTimeline helpers" in prompt
        assert "/tmp/worktree" in prompt
        assert "Precision Code Search: symbol-first" in prompt
        mock_logger.warning.assert_called_once()

    @patch(f"{_PROMPTS}.task_store")
    def test_build_conflict_context_includes_conflicting_files(
        self,
        mock_task_store: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.prompts import build_conflict_context

        mock_task_store.get_task.return_value = {
            "id": "task-1",
            "conflict_info": {
                "conflicting_files": ["backend/app/services/tools/tool_handler.py"],
                "task_branch": "task-1/main",
                "base_branch": "main",
                "error_output": "CONFLICT (content): Merge conflict in backend/app/services/tools/tool_handler.py",
            },
        }

        prompt = build_conflict_context("task-1")

        assert "Merge Conflict Context" in prompt
        assert "backend/app/services/tools/tool_handler.py" in prompt
        assert "task-1/main" in prompt
