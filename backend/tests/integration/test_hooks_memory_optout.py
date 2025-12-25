"""Integration tests for hooks API memory opt-out functionality."""

from unittest.mock import patch

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHooksMemoryOptout:
    """Integration tests for hooks API memory opt-out."""

    @patch("app.api.hooks.get_memory_config")
    @patch("app.api.hooks._ensure_project_exists")
    def test_hook_skipped_when_memory_disabled(self, mock_exists, mock_config, client):
        """Hook returns skipped when memory_enabled=false."""
        mock_exists.return_value = True
        mock_config.return_value = {
            "memory_enabled": False,
            "observations_enabled": True,
        }

        response = client.post(
            "/api/hooks/tool-use",
            json={
                "project_id": "test-project",
                "session_id": "test-session",
                "tool_name": "Write",
                "tool_output": "File written successfully. " * 50,  # Long output
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "skipped"
        assert data["skip_reason"] == "memory_disabled"
        assert data["queued"] is False

    @patch("app.api.hooks.get_memory_config")
    @patch("app.api.hooks._ensure_project_exists")
    def test_hook_skipped_when_observations_disabled(self, mock_exists, mock_config, client):
        """Hook returns skipped when observations_enabled=false."""
        mock_exists.return_value = True
        mock_config.return_value = {
            "memory_enabled": True,
            "observations_enabled": False,
        }

        response = client.post(
            "/api/hooks/tool-use",
            json={
                "project_id": "test-project",
                "session_id": "test-session",
                "tool_name": "Write",
                "tool_output": "File written successfully. " * 50,
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "skipped"
        assert data["skip_reason"] == "observations_disabled"

    @patch("app.api.hooks._ensure_project_exists")
    def test_hook_skipped_when_skip_memory_flag(self, mock_exists, client):
        """Hook returns skipped when skip_memory=true in request."""
        mock_exists.return_value = True

        response = client.post(
            "/api/hooks/tool-use",
            json={
                "project_id": "test-project",
                "session_id": "test-session",
                "tool_name": "Write",
                "tool_output": "File written successfully. " * 50,
                "skip_memory": True,  # Session-level skip flag
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "skipped"
        assert data["skip_reason"] == "session_skip_flag"

    @patch("app.api.hooks.ObservationQueue")
    @patch("app.api.hooks.get_memory_config")
    @patch("app.api.hooks._ensure_project_exists")
    @pytest.mark.asyncio
    async def test_hook_processes_normally_when_memory_enabled(
        self, mock_exists, mock_config, mock_queue_class, client
    ):
        """Hook processes normally when memory is enabled."""

        mock_exists.return_value = True
        mock_config.return_value = {
            "memory_enabled": True,
            "observations_enabled": True,
        }

        # Mock the queue enqueue - must return an awaitable
        async def mock_enqueue(*args, **kwargs):
            return {"id": "test-queue-id"}

        mock_queue = mock_queue_class.return_value
        mock_queue.enqueue = mock_enqueue

        response = client.post(
            "/api/hooks/tool-use",
            json={
                "project_id": "test-project",
                "session_id": "test-session",
                "tool_name": "Write",
                "tool_output": "File written successfully. " * 50,
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"
        assert data["queued"] is True
        assert data["queue_item_id"] == "test-queue-id"


class TestContextSessionStartOptout:
    """Integration tests for session-start context opt-out."""

    @patch("app.api.context.is_memory_feature_enabled")
    def test_returns_empty_when_injection_disabled(self, mock_enabled, client):
        """session-start returns empty block when context_injection disabled."""
        mock_enabled.return_value = False

        response = client.post("/api/projects/test-project/context/session-start", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["context_block"] == ""
        assert data["token_estimate"] == 0
        assert data["items_included"] == 0

    @patch("app.storage.memory.list_observations")
    @patch("app.storage.memory.list_diary_entries")
    @patch("app.storage.memory.count_observations_since")
    @patch("app.storage.memory.count_diary_entries_since")
    @patch("app.api.context.is_memory_feature_enabled")
    def test_returns_context_when_injection_enabled(
        self, mock_enabled, mock_diary_count, mock_obs_count, mock_list_diary, mock_list_obs, client
    ):
        """session-start returns context when enabled."""
        mock_enabled.return_value = True
        mock_diary_count.return_value = 2
        mock_obs_count.return_value = 2
        mock_list_diary.return_value = [
            {
                "id": "diary-1",
                "session_id": "test-session",
                "outcome": "success",
                "concepts": ["pattern"],
                "created_at": "2025-01-01T00:00:00",
            }
        ]
        mock_list_obs.return_value = [
            {
                "id": "obs-1",
                "observation_type": "discovery",
                "title": "Test observation",
                "created_at": "2025-01-01T00:00:00",
            }
        ]

        response = client.post("/api/projects/test-project/context/session-start", json={})

        assert response.status_code == 200
        data = response.json()
        # Just check it returns a response with correct structure
        assert "context_block" in data
        assert "items_included" in data
        assert "token_estimate" in data
