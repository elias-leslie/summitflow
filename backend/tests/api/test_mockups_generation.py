"""API regressions for project-scoped mockup asset generation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch


class TestMockupsGeneration:
    """Ensure project-scoped mockup generation preserves route context."""

    @patch("app.api.mockups_generation.mockups_storage.create_mockup")
    @patch("app.api.mockups_generation.get_mockup_directory")
    @patch("app.api.mockups_generation.generate_mockup_id")
    @patch("app.api.mockups_generation.get_sync_client")
    def test_generate_asset_uses_route_project_for_agent_hub_call(
        self,
        mock_get_client: MagicMock,
        mock_generate_id: MagicMock,
        mock_get_directory: MagicMock,
        mock_create_mockup: MagicMock,
        client: Any,
        tmp_path: Path,
    ) -> None:
        mock_generate_id.return_value = "mockup-123"
        mock_get_directory.return_value = tmp_path / "agent-hub" / "mockup-123"
        mock_create_mockup.return_value = {"mockup_id": "mockup-123"}

        mock_client = MagicMock()
        mock_client.generate_image.return_value = SimpleNamespace(
            image_base64="aGVsbG8=",
            mime_type="image/png",
        )
        mock_get_client.return_value = mock_client

        response = client.post(
            "/api/projects/agent-hub/mockups/generate-asset",
            json={
                "prompt": "Hero section illustration",
                "name": "Landing hero",
                "mockup_type": "illustration",
            },
        )

        assert response.status_code == 200
        mock_client.generate_image.assert_called_once()
        assert mock_client.generate_image.call_args.kwargs["project_id"] == "agent-hub"

    @patch("app.services.mockup_generator.revisions.mockups_storage.create_mockup")
    @patch("app.services.mockup_generator.revisions.mockups_storage.get_mockup")
    @patch("app.services.mockup_generator.revisions.get_sync_client")
    def test_rerun_mockup_uses_dedicated_agent_and_stores_child_version(
        self,
        mock_get_client: MagicMock,
        mock_get_mockup: MagicMock,
        mock_create_mockup: MagicMock,
        client: Any,
    ) -> None:
        mock_get_mockup.return_value = {
            "id": 7,
            "project_id": "agent-hub",
            "mockup_id": "mk-parent",
            "name": "Settings page",
            "description": "Original",
            "mockup_type": "page",
            "content": "<html><body>Original</body></html>",
            "task_id": None,
            "page_path": "/settings",
            "version": 1,
        }
        mock_create_mockup.return_value = {
            "id": 8,
            "project_id": "agent-hub",
            "mockup_id": "mk-child",
            "name": "Settings page revision",
            "description": "Tighter spacing",
            "mockup_type": "page",
            "file_path": None,
            "content": "<html><body>Revision</body></html>",
            "status": "generated",
            "approved_at": None,
            "approved_by": None,
            "applied_at": None,
            "task_id": None,
            "page_path": "/settings",
            "version": 2,
            "parent_mockup_id": 7,
            "generator": "agent:ui-mockup-designer",
            "generation_prompt": "Tighten spacing",
            "generation_time_ms": 123,
            "iteration_count": 2,
            "created_at": None,
            "updated_at": None,
        }

        mock_client = MagicMock()
        mock_client.complete.return_value = SimpleNamespace(
            content=(
                '{"name":"Settings page revision","description":"Tighter spacing",'
                '"content":"<html><body>Revision</body></html>",'
                '"change_summary":"Tighter spacing"}'
            ),
            model="codex/gpt-5.5",
            provider="codex",
            session_id="sess-123",
        )
        mock_get_client.return_value = mock_client

        response = client.post(
            "/api/projects/agent-hub/mockups/mk-parent/rerun",
            json={"notes": "Tighten spacing"},
        )

        assert response.status_code == 200
        assert response.json()["mockup"]["mockup_id"] == "mk-child"
        mock_client.complete.assert_called_once()
        assert mock_client.complete.call_args.kwargs["agent_slug"] == "ui-mockup-designer"
        assert mock_client.complete.call_args.kwargs["project_id"] == "agent-hub"
        mock_create_mockup.assert_called_once()
        assert mock_create_mockup.call_args.kwargs["parent_mockup_id"] == 7
        assert (
            mock_create_mockup.call_args.kwargs["generator"]
            == "agent:ui-mockup-designer"
        )
