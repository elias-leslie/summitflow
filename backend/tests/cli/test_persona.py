"""Tests for st persona CLI helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from cli.commands.persona import _get_dispatch_hint


class TestPersonaHeartbeatHelpers:
    def test_get_dispatch_hint_formats_first_running_task(self) -> None:
        client = MagicMock()
        client._global_url.return_value = "http://example.test/projects/agent-hub/pulse"
        client.get.return_value = {
            "running_tasks": [
                {
                    "id": "task-123",
                    "title": "Refactor: backend/app/main.py",
                }
            ],
            "active_owners": [
                {
                    "agent_slug": "refactor",
                    "session_id": "abcd1234-1111-2222-3333-444455556666",
                }
            ],
            "active_sessions": [],
        }

        result = _get_dispatch_hint(client, "agent-hub")

        assert result == "Dispatch detected: task-123 | refactor | abcd1234 | Refactor: backend/app/main.py"

    def test_get_dispatch_hint_returns_none_without_running_tasks(self) -> None:
        client = MagicMock()
        client._global_url.return_value = "http://example.test/projects/agent-hub/pulse"
        client.get.return_value = {
            "running_tasks": [],
            "active_owners": [],
            "active_sessions": [],
        }

        assert _get_dispatch_hint(client, "agent-hub") is None
