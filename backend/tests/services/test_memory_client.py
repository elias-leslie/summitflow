"""Unit tests for self-healing memory client header behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services.self_healing.memory_client import MemoryClient


def test_memory_client_includes_shared_agent_hub_headers() -> None:
    """Memory client should inherit standard Agent Hub auth headers."""
    with (
        patch("app.services.self_healing.memory_client.build_agent_hub_headers") as mock_headers,
    ):
        mock_headers.return_value = {
            "X-Client-Id": "client-123",
            "X-Request-Source": "source-abc",
            "X-Source-Client": "summitflow",
        }

        client = MemoryClient()

    assert client._auth_headers == {
        "X-Client-Id": "client-123",
        "X-Request-Source": "source-abc",
        "X-Source-Client": "summitflow",
    }
    mock_headers.assert_called_once_with(
        extra_headers={"X-Source-Client": "summitflow"},
    )


def test_headers_with_source_path_appends_caller_location() -> None:
    """Source-path stamping should preserve auth headers and add caller context."""
    client = MemoryClient()
    client._auth_headers = {
        "X-Client-Id": "client-123",
        "X-Request-Source": "source-abc",
        "X-Source-Client": "summitflow",
    }

    fake_stack = [
        SimpleNamespace(filename="internal.py", lineno=10),
        SimpleNamespace(filename="public.py", lineno=20),
        SimpleNamespace(filename="caller.py", lineno=30),
    ]

    with patch("app.services.self_healing.memory_client.inspect.stack", return_value=fake_stack):
        headers = client._headers_with_source_path()

    assert headers == {
        "X-Client-Id": "client-123",
        "X-Request-Source": "source-abc",
        "X-Source-Client": "summitflow",
        "X-Source-Path": "caller.py:30",
    }
