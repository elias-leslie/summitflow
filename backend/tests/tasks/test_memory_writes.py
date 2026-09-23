"""Tests for cited Agent Hub memory feedback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.memory_writes import rate_cited_memories


class TestRateCitedMemories:
    """Tests for memory citation rating."""

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_rates_each_cited_uuid(self, mock_get: MagicMock) -> None:
        client = MagicMock()
        mock_get.return_value = client

        rate_cited_memories(["uuid1", "uuid2", "uuid3"])

        assert client.rate_episode.call_count == 3

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_caps_at_10_uuids(self, mock_get: MagicMock) -> None:
        client = MagicMock()
        mock_get.return_value = client

        uuids = [f"uuid{i}" for i in range(20)]
        rate_cited_memories(uuids)

        assert client.rate_episode.call_count == 10

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_empty_list_noop(self, mock_get: MagicMock) -> None:
        rate_cited_memories([])
        mock_get.assert_not_called()

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_error_handled_silently(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = RuntimeError("fail")
        rate_cited_memories(["uuid1"])
