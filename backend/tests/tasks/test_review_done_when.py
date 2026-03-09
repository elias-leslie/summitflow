"""Tests for done_when inclusion in reviewer prompt."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestDoneWhenInReviewPrompt:
    """Tests that ai_review includes done_when criteria in the prompt."""

    @patch("app.tasks.autonomous.review.route_based_on_verdict")
    @patch("app.tasks.autonomous.review.get_sync_client")
    @patch("app.tasks.autonomous.review.get_task_spirit")
    @patch("app.tasks.autonomous.review.collect_precision_code_search_context")
    @patch("app.tasks.autonomous.review.get_git_diff")
    @patch("app.tasks.autonomous.review.task_store")
    def test_done_when_included_in_prompt(
        self,
        mock_store: MagicMock,
        mock_diff: MagicMock,
        mock_precision: MagicMock,
        mock_spirit: MagicMock,
        mock_client_fn: MagicMock,
        mock_route: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {
            "title": "Add feature X",
            "project_id": "summitflow",
            "complexity": "STANDARD",
        }
        mock_store.update_task_status = MagicMock()
        mock_diff.return_value = "+ some code changes"
        mock_precision.return_value.prompt_context = "Precision Code Search: symbol-first"
        mock_spirit.return_value = {
            "done_when": ["API returns 200 on /health", "Tests pass"],
        }

        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(
            content='{"verdict": "APPROVED", "concerns": [], "summary": "LGTM"}'
        )
        mock_client_fn.return_value = mock_client

        from app.tasks.autonomous.review import ai_review

        ai_review("task-1", "summitflow")

        # Verify the prompt includes done_when criteria
        call_args = mock_client.complete.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "Precision Code Search:" in prompt
        assert "Precision Code Search: symbol-first" in prompt
        assert "Success Criteria (done_when)" in prompt
        assert "API returns 200 on /health" in prompt
        assert "Tests pass" in prompt
        assert "verify the diff addresses each one" in prompt

    @patch("app.tasks.autonomous.review.route_based_on_verdict")
    @patch("app.tasks.autonomous.review.get_sync_client")
    @patch("app.tasks.autonomous.review.get_task_spirit")
    @patch("app.tasks.autonomous.review.collect_precision_code_search_context")
    @patch("app.tasks.autonomous.review.get_git_diff")
    @patch("app.tasks.autonomous.review.task_store")
    def test_no_spirit_shows_none_defined(
        self,
        mock_store: MagicMock,
        mock_diff: MagicMock,
        mock_precision: MagicMock,
        mock_spirit: MagicMock,
        mock_client_fn: MagicMock,
        mock_route: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {
            "title": "Fix bug",
            "project_id": "summitflow",
            "complexity": "SIMPLE",
        }
        mock_store.update_task_status = MagicMock()
        mock_diff.return_value = "+ fix"
        mock_precision.return_value.prompt_context = ""
        mock_spirit.return_value = None

        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(
            content='{"verdict": "APPROVED", "concerns": []}'
        )
        mock_client_fn.return_value = mock_client

        from app.tasks.autonomous.review import ai_review

        ai_review("task-1", "summitflow")

        prompt = mock_client.complete.call_args[1]["messages"][0]["content"]
        assert "(none defined)" in prompt

    @patch("app.tasks.autonomous.review.route_based_on_verdict")
    @patch("app.tasks.autonomous.review.get_sync_client")
    @patch("app.tasks.autonomous.review.get_task_spirit")
    @patch("app.tasks.autonomous.review.collect_precision_code_search_context")
    @patch("app.tasks.autonomous.review.get_git_diff")
    @patch("app.tasks.autonomous.review.task_store")
    def test_empty_done_when_shows_none_defined(
        self,
        mock_store: MagicMock,
        mock_diff: MagicMock,
        mock_precision: MagicMock,
        mock_spirit: MagicMock,
        mock_client_fn: MagicMock,
        mock_route: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {
            "title": "Refactor Y",
            "project_id": "summitflow",
            "complexity": "STANDARD",
        }
        mock_store.update_task_status = MagicMock()
        mock_diff.return_value = "+ refactored"
        mock_precision.return_value.prompt_context = ""
        mock_spirit.return_value = {"done_when": []}

        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(
            content='{"verdict": "APPROVED", "concerns": []}'
        )
        mock_client_fn.return_value = mock_client

        from app.tasks.autonomous.review import ai_review

        ai_review("task-1", "summitflow")

        prompt = mock_client.complete.call_args[1]["messages"][0]["content"]
        assert "(none defined)" in prompt
