"""Regression tests for project-scoped mockup Agent Hub calls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TestMockupProjectScope:
    """Mockup helpers should keep the caller's project scope."""

    @patch("app.services.mockup_generator.analysis.mockup_image.get_sync_client")
    @patch("app.services.mockup_generator.analysis.mockup_image.build_mockup_image_prompt")
    def test_generate_mockup_image_uses_passed_project_id(
        self,
        mock_prompt: MagicMock,
        mock_get_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        from app.services.mockup_generator.analysis.mockup_image import generate_mockup_image

        screenshot_path = tmp_path / "screenshot.png"
        screenshot_path.write_bytes(b"png")
        output_path = tmp_path / "out" / "mockup.png"
        mock_prompt.return_value = "prompt"
        mock_client = MagicMock()
        mock_client.generate_image.return_value = SimpleNamespace(
            image_base64="aGVsbG8=",
            mime_type="image/png",
        )
        mock_get_client.return_value = mock_client

        generate_mockup_image("agent-hub", screenshot_path, "recommendations", output_path, "/home")

        assert mock_client.generate_image.call_args.kwargs["project_id"] == "agent-hub"

    @patch("app.services.mockup_generator.analysis.vision.get_sync_client")
    @patch("app.services.mockup_generator.analysis.vision.build_design_analysis_prompt")
    def test_analyze_screenshot_with_vision_uses_passed_project_id(
        self,
        mock_prompt: MagicMock,
        mock_get_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        from app.services.mockup_generator.analysis.vision import analyze_screenshot_with_vision

        screenshot_path = tmp_path / "screenshot.png"
        screenshot_path.write_bytes(b"png")
        mock_prompt.return_value = "prompt"
        mock_client = MagicMock()
        mock_client.complete.return_value = SimpleNamespace(content="**Issue**: Contrast")
        mock_get_client.return_value = mock_client

        analyze_screenshot_with_vision("agent-hub", screenshot_path, [], "/home")

        assert mock_client.complete.call_args.kwargs["project_id"] == "agent-hub"
        assert mock_client.complete.call_args.kwargs["agent_slug"] == "designer"

    @patch("app.services.mockup_generator.analysis.vision.get_sync_client")
    def test_analyze_screenshot_with_prompt_uses_passed_project_id_and_agent_slug(
        self,
        mock_get_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        from app.services.mockup_generator.analysis.vision import analyze_screenshot_with_prompt

        screenshot_path = tmp_path / "screenshot.png"
        screenshot_path.write_bytes(b"png")
        mock_client = MagicMock()
        mock_client.complete.return_value = SimpleNamespace(content='{"passed": true}')
        mock_get_client.return_value = mock_client

        analyze_screenshot_with_prompt("agent-hub", screenshot_path, "prompt")

        assert mock_client.complete.call_args.kwargs["project_id"] == "agent-hub"
        assert mock_client.complete.call_args.kwargs["agent_slug"] == "site-checker"

    @patch("app.services.mockup_generator.renderers.gemini.get_sync_client")
    def test_generate_mockup_gemini_uses_passed_project_id(
        self,
        mock_get_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        from app.services.mockup_generator.renderers.gemini import generate_mockup_gemini

        mock_client = MagicMock()
        mock_client.generate_image.return_value = SimpleNamespace(
            image_base64="aGVsbG8=",
            mime_type="image/png",
            session_id="sess-1",
        )
        mock_get_client.return_value = mock_client

        with (
            patch(
                "app.services.mockup_generator.renderers.gemini.get_mockup_directory",
                return_value=tmp_path / "agent-hub" / "mockup-1",
            ),
            patch(
                "app.services.mockup_generator.renderers.gemini.generate_mockup_id",
                return_value="mockup-1",
            ),
            patch(
                "app.services.mockup_generator.renderers.gemini.mockups_storage.create_mockup",
                return_value={"mockup_id": "mockup-1", "id": 7},
            ),
        ):
            generate_mockup_gemini(
                project_id="agent-hub",
                explorer_entry_id=42,
                page_info={"path": "/", "name": "Home"},
                design_standard={"rules": []},
            )

        assert mock_client.generate_image.call_args.kwargs["project_id"] == "agent-hub"
