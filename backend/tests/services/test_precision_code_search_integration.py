"""Integration coverage for shared Precision Code Search prompt usage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_create_plan_includes_precision_code_search_context() -> None:
    from app.tasks.autonomous.planning import create_plan

    task = {
        "id": "task-1",
        "title": "Wire symbol retrieval",
        "description": "Use Precision Code Search in planner execution",
    }
    response = MagicMock()
    response.content = (
        '{"objective":"Ship it","subtasks":[{"subtask_id":"1.1","phase":"implementation",'
        '"subtask_type":"backend","description":"Do the work","steps":[{"description":"Add code"}],'
        '"depends_on":[]}],"constraints":[]}'
    )

    with (
        patch("app.tasks.autonomous.planning.task_store.get_task", return_value=task),
        patch(
            "app.tasks.autonomous.planning.collect_precision_code_search_context"
        ) as mock_collect,
        patch("app.tasks.autonomous.planning.get_sync_client") as mock_client_factory,
        patch("app.tasks.autonomous.planning.save_plan_to_database"),
        patch("app.tasks.autonomous.planning.route_based_on_complexity"),
    ):
        mock_collect.return_value.prompt_context = "Precision Code Search: symbol-first"
        mock_client_factory.return_value.complete.return_value = response

        result = create_plan("task-1", "summitflow")

    prompt = mock_client_factory.return_value.complete.call_args.kwargs["messages"][0]["content"]
    assert result["status"] == "completed"
    assert "## Precision Code Search" in prompt
    assert "Precision Code Search: symbol-first" in prompt


def test_discuss_task_includes_precision_code_search_context() -> None:
    from app.services.enrichment_service.discussion import discuss_task

    current_task = {
        "id": "task-1",
        "title": "Wire symbol retrieval",
        "description": "Use Precision Code Search in task discussion",
    }

    with (
        patch(
            "app.services.enrichment_service.discussion.collect_precision_code_search_context"
        ) as mock_collect,
        patch("app.services.enrichment_service.discussion.load_prompt", return_value="Prompt"),
        patch(
            "app.services.enrichment_service.discussion.parse_enrichment_response",
            return_value={"response": "Done", "changes_made": [], "updated_task": None},
        ),
        patch("app.services.agent_hub_client.AgentHubLLMClient") as mock_client_cls,
    ):
        mock_collect.return_value.prompt_context = "Precision Code Search: symbol-first"
        mock_client = mock_client_cls.return_value
        mock_client.is_available.return_value = True
        mock_client.generate.return_value.content = "{}"

        result = discuss_task(
            "summitflow",
            "task-1",
            "Should we use the symbol path by default?",
            current_task=current_task,
        )

    prompt = mock_client.generate.call_args.kwargs["prompt"]
    assert result.response == "Done"
    assert "## Precision Code Search" in prompt
    assert "Precision Code Search: symbol-first" in prompt
