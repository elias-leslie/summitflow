"""Tests for Commands API endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestExecuteCommand:
    """Tests for POST /api/commands."""

    def test_execute_command_success(self) -> None:
        """Successful command returns AI response."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Task status: all healthy", b""))
        mock_proc.returncode = 0

        with patch("app.api.commands.asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("app.api.commands.asyncio.wait_for", return_value=(b"Task status: all healthy", b"")):
                # Use a simpler approach — mock the whole endpoint flow
                pass

        # Direct approach: mock subprocess at the right level
        async def mock_create_subprocess(*args, **kwargs):  # type: ignore[no-untyped-def]
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"Task status: all healthy", b""))
            proc.returncode = 0
            return proc

        with patch("app.api.commands.asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            response = client.post(
                "/api/commands",
                json={"text": "task status", "project_id": "test-project"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["response"] == "Task status: all healthy"

    def test_execute_command_empty_text_returns_422(self) -> None:
        """Empty text is rejected by validation."""
        response = client.post(
            "/api/commands",
            json={"text": "", "project_id": "test-project"},
        )
        assert response.status_code == 422

    def test_execute_command_missing_text_returns_422(self) -> None:
        """Missing text field is rejected by validation."""
        response = client.post(
            "/api/commands",
            json={"project_id": "test-project"},
        )
        assert response.status_code == 422

    def test_execute_command_process_failure_returns_error(self) -> None:
        """Non-zero exit code returns success=False with stderr."""

        async def mock_create_subprocess(*args, **kwargs):  # type: ignore[no-untyped-def]
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b"Agent not found"))
            proc.returncode = 1
            return proc

        with patch("app.api.commands.asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            response = client.post(
                "/api/commands",
                json={"text": "do something", "project_id": "test-project"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Agent not found" in data["response"]

    def test_execute_command_st_not_found_returns_503(self) -> None:
        """FileNotFoundError (st not in PATH) returns 503."""

        async def mock_create_subprocess(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("st")

        with patch("app.api.commands.asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            response = client.post(
                "/api/commands",
                json={"text": "hello", "project_id": "test-project"},
            )

        assert response.status_code == 503
