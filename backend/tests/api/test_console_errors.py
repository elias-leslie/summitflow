"""Tests for console error capture endpoint.

Tests the POST /projects/{project_id}/errors/console endpoint.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_mock import MockerFixture

from app.api.console_errors import _compute_console_error_hash


class TestComputeConsoleErrorHash:
    """Tests for console error hash computation."""

    @pytest.mark.parametrize(
        "error,stack,expected_equal",
        [
            ("TypeError: undefined", "at foo.js:10", True),
            ("Error A", None, False),  # Different errors
            ("Error", "stack1", False),  # Different stacks
        ],
        ids=["same_input_stable", "different_errors", "different_stacks"],
    )
    def test_hash_consistency(self, error: str, stack: str | None, expected_equal: bool) -> None:
        """Test hash consistency for various inputs."""
        if expected_equal:
            # Same input produces same hash
            hash1 = _compute_console_error_hash(error, stack)
            hash2 = _compute_console_error_hash(error, stack)
            assert hash1 == hash2
        else:
            # Different inputs produce different hashes
            if stack is None:
                hash1 = _compute_console_error_hash("Error A", None)
                hash2 = _compute_console_error_hash("Error B", None)
            else:
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
    def error_request_data(self) -> dict[str, Any]:
        """Sample error request data."""
        return {
            "error": "TypeError: Cannot read property 'foo' of undefined",
            "stack": "at Bar.render (app.js:123)\nat baz (utils.js:45)",
            "url": "https://summitflow.example.com/tasks",
            "timestamp": "2026-01-18T10:30:00Z",
            "user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
        }

    @pytest.mark.asyncio
    async def test_creates_bug_task(
        self,
        mocker: MockerFixture,
        error_request_data: dict[str, Any],
    ) -> None:
        """Endpoint creates a bug task from console error."""
        from app.api.console_errors import capture_console_error
        from app.api.quality_gate_models import ConsoleErrorRequest

        mocker.patch("app.api.console_errors.validate_project_exists")
        mock_dedup = mocker.patch("app.api.console_errors.bug_task_exists_for_error")
        mock_create = mocker.patch("app.api.console_errors.create_task")
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-console123"}

        request = ConsoleErrorRequest(**error_request_data)
        result = await capture_console_error("test-project", request)

        assert result.success
        assert result.task_id == "task-console123"
        assert not result.is_duplicate

        # Verify create_task was called correctly
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["project_id"] == "test-project"
        assert call_kwargs["task_type"] == "bug"
        assert call_kwargs["priority"] == 2
        assert call_kwargs["execution_mode"] == "autonomous"
        assert "[Frontend]" in call_kwargs["title"]
        assert "TypeError" in call_kwargs["title"]

    @pytest.mark.asyncio
    async def test_includes_full_context(
        self,
        mocker: MockerFixture,
        error_request_data: dict[str, Any],
    ) -> None:
        """Task description includes full error context."""
        from app.api.console_errors import capture_console_error
        from app.api.quality_gate_models import ConsoleErrorRequest

        mocker.patch("app.api.console_errors.validate_project_exists")
        mock_dedup = mocker.patch("app.api.console_errors.bug_task_exists_for_error")
        mock_create = mocker.patch("app.api.console_errors.create_task")
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        request = ConsoleErrorRequest(**error_request_data)
        await capture_console_error("summitflow", request)

        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]

        assert "TypeError: Cannot read property" in description
        assert "at Bar.render" in description
        assert "https://summitflow.example.com/tasks" in description
        assert "2026-01-18T10:30:00Z" in description
        assert "Mozilla/5.0" in description

    @pytest.mark.asyncio
    async def test_skips_duplicate(
        self,
        mocker: MockerFixture,
        error_request_data: dict[str, Any],
    ) -> None:
        """Duplicate errors don't create new tasks."""
        from app.api.console_errors import capture_console_error
        from app.api.quality_gate_models import ConsoleErrorRequest

        mocker.patch("app.api.console_errors.validate_project_exists")
        mock_dedup = mocker.patch("app.api.console_errors.bug_task_exists_for_error")
        mock_create = mocker.patch("app.api.console_errors.create_task")
        mock_dedup.return_value = True  # Task already exists

        request = ConsoleErrorRequest(**error_request_data)
        result = await capture_console_error("summitflow", request)

        assert result.success
        assert result.task_id is None
        assert result.is_duplicate
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_no_stack(
        self,
        mocker: MockerFixture,
    ) -> None:
        """Works when stack trace is not provided."""
        from app.api.console_errors import capture_console_error
        from app.api.quality_gate_models import ConsoleErrorRequest

        mocker.patch("app.api.console_errors.validate_project_exists")
        mock_dedup = mocker.patch("app.api.console_errors.bug_task_exists_for_error")
        mock_create = mocker.patch("app.api.console_errors.create_task")
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        request = ConsoleErrorRequest(
            error="Simple error",
            url="https://example.com",
            timestamp="2026-01-18T10:00:00Z",
        )
        result = await capture_console_error("summitflow", request)

        assert result.success
        call_kwargs = mock_create.call_args[1]
        description = call_kwargs["description"]
        assert "Stack Trace" not in description

    @pytest.mark.parametrize(
        "content_type,content,expected_check",
        [
            ("error", "A" * 200, "title"),  # Long error -> title truncated
            ("stack", "at frame\n" * 500, "description"),  # Long stack -> description truncated
        ],
        ids=["long_error", "long_stack"],
    )
    @pytest.mark.asyncio
    async def test_truncates_long_content(
        self,
        mocker: MockerFixture,
        content_type: str,
        content: str,
        expected_check: str,
    ) -> None:
        """Long error messages and stacks are truncated."""
        from app.api.console_errors import capture_console_error
        from app.api.quality_gate_models import ConsoleErrorRequest

        mocker.patch("app.api.console_errors.validate_project_exists")
        mock_dedup = mocker.patch("app.api.console_errors.bug_task_exists_for_error")
        mock_create = mocker.patch("app.api.console_errors.create_task")
        mock_dedup.return_value = False
        mock_create.return_value = {"id": "task-123"}

        if content_type == "error":
            request = ConsoleErrorRequest(
                error=content,
                url="https://example.com",
                timestamp="2026-01-18T10:00:00Z",
            )
        else:
            request = ConsoleErrorRequest(
                error="Error",
                stack=content,
                url="https://example.com",
                timestamp="2026-01-18T10:00:00Z",
            )

        await capture_console_error("summitflow", request)

        call_kwargs = mock_create.call_args[1]
        if expected_check == "title":
            title = call_kwargs["title"]
            assert len(title) < 120
            assert "..." in title
        else:
            description = call_kwargs["description"]
            assert len(description) < 3000
