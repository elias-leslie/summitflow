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
        # build_failures_block returns empty string (steps layer removed)
        assert "subtask 1.1" in prompt
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
    @patch(
        f"{_PROMPTS}._build_precision_code_search_block",
        return_value=(
            "\n# Precision Code Search\nPrecision Code Search: symbol-first\n\n"
            "Use the Precision Code Search block as the first code-navigation pass."
        ),
    )
    @patch(f"{_PROMPTS}.get_project_root_path", return_value="/srv/workspaces/projects/agent-hub")
    @patch(f"{_PROMPTS}.get_handoff_context", return_value={})
    @patch(f"{_PROMPTS}.task_store")
    @patch(f"{_PROMPTS}.get_task_spirit")
    @patch(f"{_PROMPTS}.logger")
    @patch(f"{_PROMPTS}.get_prompt_template")
    def test_build_subtask_prompt_uses_transient_fallback_template(
        self,
        mock_get_prompt_template: MagicMock,
        mock_logger: MagicMock,
        mock_get_task_spirit: MagicMock,
        mock_task_store: MagicMock,
        _mock_project_root: MagicMock,
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
            "done_when": ["No regressions", "Keep render output stable"],
            "context": {
                "files_to_modify": ["frontend/components/ActivityTimeline.tsx"],
                "files_to_create": ["frontend/components/ActivityTimelineParts.tsx"],
            },
        }
        mock_task_store.get_task.return_value = {
            "id": "task-1",
            "description": "Reduce the component size while preserving behavior",
        }

        prompt = build_subtask_prompt(
            task_id="task-1",
            subtask={
                "subtask_id": "1.1",
                "description": "Extract reusable ActivityTimeline helpers",
                "steps_from_table": [{"step_number": 1, "description": "Keep output stable"}],
            },
            project_id="agent-hub",
            project_path="/tmp/checkout",
        )

        assert "Reduce the component size while preserving behavior" in prompt
        assert "Completion Criteria" in prompt
        assert "No regressions" in prompt
        assert "Expected Scope" in prompt
        assert "frontend/components/ActivityTimeline.tsx" in prompt
        assert "Extract reusable ActivityTimeline helpers" in prompt
        assert "/tmp/checkout" in prompt
        assert "Precision Code Search: symbol-first" in prompt
        assert "Use the Precision Code Search block as the first code-navigation pass." in prompt
        mock_logger.warning.assert_called_once()

    @patch(f"{_PROMPTS}.build_health_context", return_value="")
    @patch(f"{_PROMPTS}.build_conflict_context", return_value="")
    @patch(f"{_PROMPTS}.build_resume_context", return_value="")
    @patch(f"{_PROMPTS}._build_precision_code_search_block", return_value="")
    @patch(f"{_PROMPTS}.get_project_root_path", return_value="/srv/workspaces/projects/agent-hub")
    @patch(f"{_PROMPTS}.get_handoff_context", return_value={})
    @patch(f"{_PROMPTS}.task_store")
    @patch(f"{_PROMPTS}.get_task_spirit")
    @patch(f"{_PROMPTS}.get_prompt_template", return_value="{steps_block}")
    def test_build_subtask_prompt_uses_plan_context_steps_when_step_rows_missing(
        self,
        _mock_template: MagicMock,
        mock_get_task_spirit: MagicMock,
        mock_task_store: MagicMock,
        _mock_project_root: MagicMock,
        _mock_handoff: MagicMock,
        _mock_precision: MagicMock,
        _mock_resume: MagicMock,
        _mock_conflict: MagicMock,
        _mock_health: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.prompts import build_subtask_prompt

        mock_get_task_spirit.return_value = {"done_when": [], "context": {}}
        mock_task_store.get_task.return_value = {"id": "task-1", "description": "Do the work"}

        prompt = build_subtask_prompt(
            task_id="task-1",
            subtask={
                "subtask_id": "1.1",
                "description": "Apply the refactor",
                "steps": [{"step_number": 1, "description": "Preserve behavior"}],
            },
            project_id="agent-hub",
            project_path="/tmp/checkout",
        )

        assert "Preserve behavior" in prompt

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

    @patch(f"{_PROMPTS}.build_health_context", return_value="")
    @patch(f"{_PROMPTS}.build_conflict_context", return_value="")
    @patch(f"{_PROMPTS}.build_resume_context", return_value="")
    @patch(f"{_PROMPTS}._build_precision_code_search_block", return_value="")
    @patch(f"{_PROMPTS}.get_project_root_path", return_value="/srv/workspaces/projects/summitflow")
    @patch(f"{_PROMPTS}.get_handoff_context", return_value={})
    @patch(f"{_PROMPTS}.task_store")
    @patch(f"{_PROMPTS}.get_task_spirit")
    @patch(
        f"{_PROMPTS}.get_prompt_template",
        return_value="{objective}{done_when_block}{scope_block}{contract_block}{steps_block}",
    )
    def test_build_subtask_prompt_includes_execution_contract_block(
        self,
        _mock_template: MagicMock,
        mock_get_task_spirit: MagicMock,
        mock_task_store: MagicMock,
        _mock_project_root: MagicMock,
        _mock_handoff: MagicMock,
        _mock_precision: MagicMock,
        _mock_resume: MagicMock,
        _mock_conflict: MagicMock,
        _mock_health: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.prompts import build_subtask_prompt

        mock_get_task_spirit.return_value = {
            "done_when": ["Keep the dashboard stable"],
            "context": {
                "files_to_modify": ["frontend/app/dashboard/page.tsx"],
                "execution_contract": {
                    "mode": "runtime_eval_plus_design",
                    "target_urls": ["/app/dashboard"],
                    "user_flows": [
                        {
                            "title": "Open dashboard",
                            "actions": ["Visit /app/dashboard"],
                            "expected_outcomes": ["Dashboard content renders"],
                        }
                    ],
                    "api_checks": [{"method": "GET", "path": "/dashboard", "status": 200}],
                    "design_criteria": {"rubric": ["craft", "usability"]},
                    "risk_notes": ["Dense card layout can regress visually"],
                },
            },
        }
        mock_task_store.get_task.return_value = {"id": "task-1", "description": "Refresh dashboard UX"}

        prompt = build_subtask_prompt(
            task_id="task-1",
            subtask={
                "subtask_id": "1.1",
                "description": "Refresh dashboard UX",
                "steps_from_table": [{"step_number": 1, "description": "Update layout"}],
            },
            project_id="summitflow",
            project_path="/tmp/checkout",
        )

        assert "Execution Contract" in prompt
        assert "runtime_eval_plus_design" in prompt
        assert "/app/dashboard" in prompt
        assert "Open dashboard" in prompt
        assert "Dense card layout can regress visually" in prompt

    @patch(f"{_PROMPTS}.build_health_context", return_value="")
    @patch(f"{_PROMPTS}.build_conflict_context", return_value="")
    @patch(f"{_PROMPTS}.build_resume_context", return_value="")
    @patch(f"{_PROMPTS}._build_precision_code_search_block", return_value="")
    @patch(f"{_PROMPTS}.get_project_root_path", return_value="/srv/workspaces/projects/test2")
    @patch(f"{_PROMPTS}.get_handoff_context", return_value={})
    @patch(f"{_PROMPTS}.task_store")
    @patch(f"{_PROMPTS}.get_task_spirit")
    @patch(
        f"{_PROMPTS}.get_prompt_template",
        return_value="{scope_block}\n# Working Directory\n{project_path}",
    )
    def test_build_subtask_prompt_remaps_absolute_project_root_scope_paths_to_relative(
        self,
        _mock_template: MagicMock,
        mock_get_task_spirit: MagicMock,
        mock_task_store: MagicMock,
        _mock_project_root: MagicMock,
        _mock_handoff: MagicMock,
        _mock_precision: MagicMock,
        _mock_resume: MagicMock,
        _mock_conflict: MagicMock,
        _mock_health: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.prompts import build_subtask_prompt

        mock_get_task_spirit.return_value = {
            "done_when": [],
            "context": {
                "files_to_modify": [
                    "/srv/workspaces/projects/test2/backend/app/main.py",
                    "frontend/server.py",
                ],
                "files_to_create": [
                    "/srv/workspaces/projects/test2/frontend/app/page.tsx",
                ],
            },
        }
        mock_task_store.get_task.return_value = {"id": "task-1", "description": "Fix testbed bootstrap"}

        prompt = build_subtask_prompt(
            task_id="task-1",
            subtask={
                "subtask_id": "1.1",
                "description": "Repair the bootstrap path handling",
                "steps_from_table": [{"step_number": 1, "description": "Keep lane-safe scope paths"}],
            },
            project_id="test2",
            project_path="/home/kasadis//.local/share/st/checkpoints/test2/task-1",
        )

        assert "backend/app/main.py" in prompt
        assert "frontend/server.py" in prompt
        assert "frontend/app/page.tsx" in prompt
        assert "/srv/workspaces/projects/test2/backend/app/main.py" not in prompt
        assert "/srv/workspaces/projects/test2/frontend/app/page.tsx" not in prompt
