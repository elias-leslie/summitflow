"""Tests for console error capture endpoint.

Tests the POST /projects/{project_id}/errors/console endpoint.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.quality_gate import _compute_console_error_hash


class TestComputeConsoleErrorHash:
    """Tests for console error hash computation."""

    def test_hash_is_stable(self) -> None:
        """Same input produces same hash."""
        hash1 = _compute_console_error_hash("TypeError: undefined", "at foo.js:10")
        hash2 = _compute_console_error_hash("TypeError: undefined", "at foo.js:10")
        assert hash1 == hash2

    def test_different_errors_different_hashes(self) -> None:
        """Different errors produce different hashes."""
        hash1 = _compute_console_error_hash("Error A", None)
        hash2 = _compute_console_error_hash("Error B", None)
        assert hash1 != hash2

    def test_different_stacks_different_hashes(self) -> None:
        """Different stacks produce different hashes."""
        hash1 = _compute_console_error_hash("Error", "stack1")
        hash2 = _compute_console_error_hash("Error", "stack2")
        assert hash1 != hash2

    def test_hash_length(self) -> None:
        """Hash is 16 characters."""
        hash_val = _compute_console_error_hash("error", "stack")
        assert len(hash_val) == 16

    def test_none_stack_handled(self) -> None:
        """None stack is handled gracefully."""
        hash_val = _compute_console_error_hash("error", None)
        assert len(hash_val) == 16


class TestCaptureConsoleErrorEndpoint:
    """Tests for the capture_console_error endpoint."""

    @pytest.fixture
    def mock_project_exists(self) -> MagicMock:
        """Mock project validation to pass."""
        with patch("app.api.quality_gate._validate_project_exists"):
            yield

    @pytest.fixture
    def error_request_data(self) -> dict:
        """Sample error request data."""
        return {
            "error": "TypeError: Cannot read property 'foo' of undefined",
            "stack": "at Bar.render (app.js:123)\nat baz (utils.js:45)",
            "url": "https://dev.summitflow.dev/tasks",
            "timestamp": "2026-01-18T10:30:00Z",
            "user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
        }

    @patch("app.api.quality_gate.create_task")
    @patch("app.api.quality_gate.bug_task_exists_for_error")
    @patch("app.api.quality_gate._validate_project_exists")
    @pytest.mark.asyncio
    async def test_creates_bug_task(
        self,
        mock_validate: MagicMock,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
        error_request_data: dict,
    ) -> None:
        """Endpoint creates a bug task from console error."""
        from app.api.quality_gate import ConsoleErrorRequest, capture_console_error

        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-console123"}

        request = ConsoleErrorRequest(**error_request_data)
        result = await capture_console_error("summitflow", request)

        assert result.success is True
        assert result.task_id == "task-console123"
        assert result.is_duplicate is False

        # Verify create_task was called correctly
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["project_id"] == "test-project"
        assert call_kwargs["task_type"] == "bug"
        assert call_kwargs["priority"] == 2
        assert call_kwargs["autonomous"] is True
        assert "[Frontend]" in call_kwargs["title"]
        assert "TypeError" in call_kwargs["title"]

    @patch("app.api.quality_gate.create_task")
    @patch("app.api.quality_gate.bug_task_exists_for_error")
    @patch("app.api.quality_gate._validate_project_exists")
    @pytest.mark.asyncio
    async def test_includes_full_context(
        self,
        mock_validate: MagicMock,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
        error_request_data: dict,
    ) -> None:
        """Task description includes full error context."""
        from app.api.quality_gate import ConsoleErrorRequest, capture_console_error

        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        request = ConsoleErrorRequest(**error_request_data)
        await capture_console_error("summitflow", request)

        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]

        assert "TypeError: Cannot read property" in description
        assert "at Bar.render" in description
        assert "https://dev.summitflow.dev/tasks" in description
        assert "2026-01-18T10:30:00Z" in description
        assert "Mozilla/5.0" in description

    @patch("app.api.quality_gate.create_task")
    @patch("app.api.quality_gate.bug_task_exists_for_error")
    @patch("app.api.quality_gate._validate_project_exists")
    @pytest.mark.asyncio
    async def test_skips_duplicate(
        self,
        mock_validate: MagicMock,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
        error_request_data: dict,
    ) -> None:
        """Duplicate errors don't create new tasks."""
        from app.api.quality_gate import ConsoleErrorRequest, capture_console_error

        mock_dedup.return_value = True  # Task already exists

        request = ConsoleErrorRequest(**error_request_data)
        result = await capture_console_error("summitflow", request)

        assert result.success is True
        assert result.task_id is None
        assert result.is_duplicate is True
        mock_create.assert_not_called()

    @patch("app.api.quality_gate.create_task")
    @patch("app.api.quality_gate.bug_task_exists_for_error")
    @patch("app.api.quality_gate._validate_project_exists")
    @pytest.mark.asyncio
    async def test_handles_no_stack(
        self,
        mock_validate: MagicMock,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Works when stack trace is not provided."""
        from app.api.quality_gate import ConsoleErrorRequest, capture_console_error

        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        request = ConsoleErrorRequest(
            error="Simple error",
            url="https://example.com",
            timestamp="2026-01-18T10:00:00Z",
        )
        result = await capture_console_error("summitflow", request)

        assert result.success is True
        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]
        assert "Stack Trace" not in description

    @patch("app.api.quality_gate.create_task")
    @patch("app.api.quality_gate.bug_task_exists_for_error")
    @patch("app.api.quality_gate._validate_project_exists")
    @pytest.mark.asyncio
    async def test_truncates_long_error(
        self,
        mock_validate: MagicMock,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Long error messages are truncated in title."""
        from app.api.quality_gate import ConsoleErrorRequest, capture_console_error

        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        long_error = "A" * 200  # Very long message
        request = ConsoleErrorRequest(
            error=long_error,
            url="https://example.com",
            timestamp="2026-01-18T10:00:00Z",
        )
        await capture_console_error("summitflow", request)

        call_kwargs = mock_create.call_args[1]
        title = call_kwargs["title"]

        # Title should be truncated
        assert len(title) < 120
        assert "..." in title

    @patch("app.api.quality_gate.create_task")
    @patch("app.api.quality_gate.bug_task_exists_for_error")
    @patch("app.api.quality_gate._validate_project_exists")
    @pytest.mark.asyncio
    async def test_truncates_long_stack(
        self,
        mock_validate: MagicMock,
        mock_dedup: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Very long stack traces are truncated in description."""
        from app.api.quality_gate import ConsoleErrorRequest, capture_console_error

        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        long_stack = "at frame\n" * 500  # Very long stack
        request = ConsoleErrorRequest(
            error="Error",
            stack=long_stack,
            url="https://example.com",
            timestamp="2026-01-18T10:00:00Z",
        )
        await capture_console_error("summitflow", request)

        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]

        # Stack in description should be truncated to ~2000 chars
        assert len(description) < 3000
