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
