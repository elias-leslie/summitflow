"""Unit tests for context_access storage."""

from unittest.mock import MagicMock, patch


class TestGetPatternEffectiveness:
    """Tests for pattern effectiveness query."""

    def test_returns_empty_when_no_data(self):
        """Returns empty list when no pattern access data exists."""
        with patch("app.storage.context_access.get_connection") as mock_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.__enter__ = MagicMock(return_value=mock_conn.return_value)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.cursor.return_value = mock_cursor

            from app.storage.context_access import get_pattern_effectiveness

            result = get_pattern_effectiveness("test-project", days=30)

            assert result == []

    def test_calculates_success_rate(self):
        """Calculates correct success rate from outcome counts."""
        with patch("app.storage.context_access.get_connection") as mock_conn:
            mock_cursor = MagicMock()
            # pattern_id, total_access, success, partial, failure, injection, api, cli, sessions
            mock_cursor.fetchall.return_value = [
                ("pattern-123", 10, 7, 2, 1, 8, 2, 0, 5),  # 70% success
                ("pattern-456", 5, 1, 1, 3, 5, 0, 0, 3),  # 20% success
            ]
            mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.__enter__ = MagicMock(return_value=mock_conn.return_value)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.cursor.return_value = mock_cursor

            from app.storage.context_access import get_pattern_effectiveness

            result = get_pattern_effectiveness("test-project", days=30)

            assert len(result) == 2

            # First pattern: 7 success out of 10 with outcomes
            assert result[0]["pattern_id"] == "pattern-123"
            assert result[0]["success_rate"] == 0.7
            assert result[0]["total_access"] == 10
            assert result[0]["unique_sessions"] == 5

            # Second pattern: 1 success out of 5 with outcomes
            assert result[1]["pattern_id"] == "pattern-456"
            assert result[1]["success_rate"] == 0.2


class TestGetAccessSummary:
    """Tests for access summary query."""

    def test_returns_correct_structure(self):
        """Returns properly structured summary."""
        with patch("app.storage.context_access.get_connection") as mock_conn:
            mock_cursor = MagicMock()
            # total, patterns, obs, diary, injection, api, cli, success, partial, failure, pending, sessions
            mock_cursor.fetchone.return_value = (100, 80, 15, 5, 70, 25, 5, 30, 20, 10, 40, 25)
            mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.__enter__ = MagicMock(return_value=mock_conn.return_value)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.cursor.return_value = mock_cursor

            from app.storage.context_access import get_access_summary

            result = get_access_summary("test-project", days=7)

            assert result["project_id"] == "test-project"
            assert result["days"] == 7
            assert result["total_access"] == 100
            assert result["by_entity_type"]["pattern"] == 80
            assert result["by_access_source"]["injection"] == 70
            assert result["by_outcome"]["success"] == 30
            assert result["unique_sessions"] == 25
