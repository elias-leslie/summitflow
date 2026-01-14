"""Tests for AgentHubStreamingClient.

Covers:
- Connection setup with session ID tracking
- Streaming content via async iterator
- Cancellation via cancel() method
- Result accumulation
- Error handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from agent_hub.models import StreamChunk
from app.services.agent_hub_client import (
    AgentHubStreamingClient,
    StreamingResult,
)


class TestStreamingResult:
    """Tests for StreamingResult dataclass."""

    def test_default_values(self):
        """Test StreamingResult default values."""
        result = StreamingResult(content="Hello", session_id="sess-123")
        assert result.content == "Hello"
        assert result.session_id == "sess-123"
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.finish_reason == "end_turn"
        assert result.cancelled is False
        assert result.error is None

    def test_all_fields(self):
        """Test StreamingResult with all fields."""
        result = StreamingResult(
            content="Test content",
            session_id="sess-456",
            input_tokens=100,
            output_tokens=50,
            finish_reason="max_tokens",
            cancelled=True,
            error="Test error",
        )
        assert result.content == "Test content"
        assert result.session_id == "sess-456"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.finish_reason == "max_tokens"
        assert result.cancelled is True
        assert result.error == "Test error"


class TestAgentHubStreamingClient:
    """Tests for AgentHubStreamingClient class."""

    @pytest.fixture
    def client(self):
        """Create a streaming client for testing."""
        return AgentHubStreamingClient(
            base_url="http://test-hub:8003",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_connect_generates_session_id(self, client: AgentHubStreamingClient):
        """Test connect() generates session ID if not provided."""
        session_id = await client.connect(
            model="gemini-3-flash-preview",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert session_id is not None
        assert len(session_id) > 0
        assert client.session_id == session_id

    @pytest.mark.asyncio
    async def test_connect_uses_provided_session_id(self, client: AgentHubStreamingClient):
        """Test connect() uses provided session ID."""
        session_id = await client.connect(
            model="gemini-3-flash-preview",
            messages=[{"role": "user", "content": "Hello"}],
            session_id="custom-session-123",
        )
        assert session_id == "custom-session-123"
        assert client.session_id == "custom-session-123"

    @pytest.mark.asyncio
    async def test_stream_without_connect_raises(self, client: AgentHubStreamingClient):
        """Test stream() raises error if connect() not called."""
        with pytest.raises(RuntimeError, match="Call connect\\(\\) before stream\\(\\)"):
            async for _ in client.stream():
                pass

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, client: AgentHubStreamingClient):
        """Test stream() yields chunks from Agent Hub."""

        # Setup mock async generator
        async def mock_stream(*args, **kwargs):
            yield StreamChunk(type="content", content="Hello ")
            yield StreamChunk(type="content", content="world")
            yield StreamChunk(
                type="done",
                finish_reason="end_turn",
                input_tokens=10,
                output_tokens=2,
            )

        mock_async_client = AsyncMock()
        mock_async_client.stream = mock_stream

        with patch.object(client, "_get_client", return_value=mock_async_client):
            await client.connect(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
            )

            chunks = []
            async for chunk in client.stream():
                chunks.append(chunk)

            assert len(chunks) == 3
            assert chunks[0].type == "content"
            assert chunks[0].content == "Hello "
            assert chunks[1].type == "content"
            assert chunks[1].content == "world"
            assert chunks[2].type == "done"
            assert chunks[2].finish_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_stream_accumulates_content(self, client: AgentHubStreamingClient):
        """Test stream() accumulates content for result."""

        async def mock_stream(*args, **kwargs):
            yield StreamChunk(type="content", content="Hello ")
            yield StreamChunk(type="content", content="world")
            yield StreamChunk(
                type="done",
                finish_reason="end_turn",
                input_tokens=10,
                output_tokens=2,
            )

        mock_async_client = AsyncMock()
        mock_async_client.stream = mock_stream

        with patch.object(client, "_get_client", return_value=mock_async_client):
            await client.connect(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
            )

            async for _ in client.stream():
                pass

            result = client.get_result()
            assert result.content == "Hello world"
            assert result.input_tokens == 10
            assert result.output_tokens == 2
            assert result.finish_reason == "end_turn"
            assert result.cancelled is False

    @pytest.mark.asyncio
    async def test_cancel_sets_flag(self, client: AgentHubStreamingClient):
        """Test cancel() sets cancellation flag."""
        mock_async_client = AsyncMock()
        mock_async_client.cancel_stream = AsyncMock(
            return_value={"cancelled": True, "input_tokens": 5, "output_tokens": 3}
        )

        with patch.object(client, "_get_client", return_value=mock_async_client):
            await client.connect(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
            )

            result = await client.cancel()
            assert result["cancelled"] is True
            assert client._cancel_requested is True

    @pytest.mark.asyncio
    async def test_cancel_without_session_returns_error(self, client: AgentHubStreamingClient):
        """Test cancel() without active session returns error."""
        result = await client.cancel()
        assert result["cancelled"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_stream_stops_on_cancel(self, client: AgentHubStreamingClient):
        """Test stream() yields cancelled chunk when cancel requested."""
        # Track how many chunks were actually consumed
        consumed_chunks = []

        async def mock_stream(*args, **kwargs):
            yield StreamChunk(type="content", content="First")
            # Simulate cancel being called during streaming
            client._cancel_requested = True
            yield StreamChunk(type="content", content="Second")
            yield StreamChunk(type="done", finish_reason="end_turn")

        mock_async_client = AsyncMock()
        mock_async_client.stream = mock_stream

        with patch.object(client, "_get_client", return_value=mock_async_client):
            await client.connect(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
            )

            async for chunk in client.stream():
                consumed_chunks.append(chunk)
                if chunk.type == "cancelled":
                    break

            # Should have: content, cancelled (stops there)
            assert len(consumed_chunks) == 2
            assert consumed_chunks[0].type == "content"
            assert consumed_chunks[1].type == "cancelled"

    @pytest.mark.asyncio
    async def test_context_manager(self, client: AgentHubStreamingClient):
        """Test async context manager usage."""
        mock_async_client = AsyncMock()
        mock_async_client.close = AsyncMock()

        with patch.object(client, "_client", mock_async_client):
            async with client:
                pass

            mock_async_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_resets_state(self, client: AgentHubStreamingClient):
        """Test close() resets connected state."""
        await client.connect(
            model="gemini-3-flash-preview",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert client._connected is True

        await client.close()
        assert client._connected is False
        assert client._client is None
