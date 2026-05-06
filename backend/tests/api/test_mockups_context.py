"""API regressions for token-efficient mockup artifact context."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


def _mockup_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": 7,
        "project_id": "summitflow",
        "mockup_id": "mk-123456789abc",
        "name": "Tasks page",
        "description": "Jenny-managed task board",
        "mockup_type": "page",
        "file_path": None,
        "content": "<html><body><main>full html should stay out by default</main></body></html>",
        "status": "generated",
        "approved_at": None,
        "approved_by": None,
        "applied_at": None,
        "task_id": "task-123",
        "page_path": "/projects/summitflow/tasks",
        "version": 2,
        "parent_mockup_id": None,
        "generator": "surface-editor",
        "generation_prompt": "Surface edit",
        "generation_time_ms": None,
        "iteration_count": 2,
        "metadata": {
            "annotations": [
                {
                    "id": "ann-1",
                    "note": "Remove noisy status panel",
                    "element_path": "main > aside:nth-of-type(1)",
                    "element_label": "aside.status",
                }
            ],
            "token_policy": {"default_context": "compact"},
        },
        "created_at": None,
        "updated_at": "2026-05-06T09:00:00+00:00",
    }
    payload.update(overrides)
    return payload


class TestMockupsContext:
    """Mockup context should be compact unless full content is requested."""

    @patch("app.api.mockups_crud.mockups_storage.get_mockup")
    def test_context_endpoint_uses_metadata_without_full_content(
        self,
        mock_get_mockup: MagicMock,
        client: Any,
    ) -> None:
        mock_get_mockup.return_value = _mockup_payload()

        response = client.get(
            "/api/projects/summitflow/mockups/mk-123456789abc/context"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["mockup_id"] == "mk-123456789abc"
        assert data["content_included"] is False
        assert data["content"] is None
        assert data["annotation_count"] == 1
        assert data["annotations"][0]["element_label"] == "aside.status"
        assert "Remove noisy status panel" in data["compact_summary"]
        assert "<html>" not in data["compact_summary"]

    @patch("app.api.mockups_crud.mockups_storage.get_mockup")
    def test_context_endpoint_can_include_full_content_on_request(
        self,
        mock_get_mockup: MagicMock,
        client: Any,
    ) -> None:
        mock_get_mockup.return_value = _mockup_payload()

        response = client.get(
            "/api/projects/summitflow/mockups/mk-123456789abc/context?include_content=true"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content_included"] is True
        assert data["content"].startswith("<html>")

    @patch("app.api.mockups_crud.mockups_storage.create_mockup")
    def test_create_mockup_accepts_metadata(
        self,
        mock_create_mockup: MagicMock,
        client: Any,
    ) -> None:
        mock_create_mockup.return_value = _mockup_payload()

        response = client.post(
            "/api/projects/summitflow/mockups",
            json={
                "name": "Tasks page",
                "mockup_type": "page",
                "content": "<html></html>",
                "metadata": {
                    "annotations": [{"note": "Tighten task cards"}],
                    "token_policy": {"default_context": "compact"},
                },
            },
        )

        assert response.status_code == 201
        assert (
            response.json()["metadata"]["annotations"][0]["note"]
            == "Remove noisy status panel"
        )
        assert mock_create_mockup.call_args.kwargs["metadata"] == {
            "annotations": [{"note": "Tighten task cards"}],
            "token_policy": {"default_context": "compact"},
        }
