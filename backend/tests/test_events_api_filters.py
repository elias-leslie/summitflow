"""Tests for event API filter extensions (after + event_type).

Covers:
- get_events_with_filters() with after timestamp filter
- get_events_with_filters() with event_type filter
- get_events_with_filters() with combined after + event_type filters
- get_events_by_trace() with after timestamp filter
- API endpoint query parameter acceptance
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.storage.events import get_events_by_trace, get_events_with_filters


class TestGetEventsWithFiltersAfter:
    """Tests for get_events_with_filters() with after timestamp filter."""

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_after_builds_correct_sql_condition(
        self, mock_get_connection: MagicMock
    ):
        """Test that after timestamp parameter builds correct SQL WHERE condition."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock cursor.fetchone() for COUNT query
        mock_cursor.fetchone.side_effect = [
            (5,),  # total count
            None,  # summary query (no rows)
        ]
        # Mock cursor.fetchall() for events query and summary
        mock_cursor.fetchall.side_effect = [
            [],  # summary query
            [],  # events query
        ]

        after_timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)
        result = get_events_with_filters(
            project_id="test-project", after=after_timestamp
        )

        # Verify execute was called with correct SQL and params
        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 3  # COUNT, summary GROUP BY, events SELECT

        # Check COUNT query
        count_sql, count_params = calls[0].args
        assert "timestamp > %s" in count_sql
        assert "test-project" in count_params
        assert after_timestamp in count_params

        # Check events query
        events_sql, events_params = calls[2].args
        assert "timestamp > %s" in events_sql
        assert after_timestamp in events_params

        assert result["total"] == 5
        assert result["events"] == []

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_after_excludes_older_events(
        self, mock_get_connection: MagicMock
    ):
        """Test that after filter excludes events at or before the timestamp."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        after_timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)
        older_timestamp = datetime(2026, 2, 14, 9, 0, 0, tzinfo=UTC)
        newer_timestamp = datetime(2026, 2, 14, 11, 0, 0, tzinfo=UTC)

        # Mock response with two events: one before, one after
        mock_cursor.fetchone.side_effect = [
            (1,),  # total count
            None,
        ]
        mock_cursor.fetchall.side_effect = [
            [("info", 1)],  # summary
            [
                # Only the newer event should be in results
                (
                    "evt-1",
                    "test-project",
                    "test-trace-id",
                    "span-1",
                    None,
                    "log",
                    "Event",
                    "system",
                    "info",
                    "user",
                    "Newer event",
                    {"key": "value"},
                    newer_timestamp,
                )
            ],
        ]

        result = get_events_with_filters(
            project_id="test-project", after=after_timestamp
        )

        assert result["total"] == 1
        assert len(result["events"]) == 1
        assert result["events"][0]["timestamp"] == newer_timestamp
        assert result["events"][0]["message"] == "Newer event"

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_after_none_includes_all_events(
        self, mock_get_connection: MagicMock
    ):
        """Test that after=None includes all events without timestamp filter."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [(3,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        result = get_events_with_filters(project_id="test-project", after=None)

        # Verify SQL does NOT contain timestamp filter
        calls = mock_cursor.execute.call_args_list
        count_sql, count_params = calls[0].args
        assert "timestamp >" not in count_sql
        assert len(count_params) == 1  # Only project_id


class TestGetEventsWithFiltersEventType:
    """Tests for get_events_with_filters() with event_type filter."""

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_event_type_builds_correct_sql_condition(
        self, mock_get_connection: MagicMock
    ):
        """Test that event_type parameter builds correct SQL WHERE condition."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [(2,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        result = get_events_with_filters(
            project_id="test-project", event_type="state_change"
        )

        # Verify execute was called with correct SQL and params
        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 3

        # Check COUNT query
        count_sql, count_params = calls[0].args
        assert "event_type = %s" in count_sql
        assert "test-project" in count_params
        assert "state_change" in count_params

        # Check events query
        events_sql, events_params = calls[2].args
        assert "event_type = %s" in events_sql
        assert "state_change" in events_params

        assert result["total"] == 2

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_event_type_filters_correctly(
        self, mock_get_connection: MagicMock
    ):
        """Test that event_type filter returns only matching event types."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)

        mock_cursor.fetchone.side_effect = [(2,), None]
        mock_cursor.fetchall.side_effect = [
            [("info", 2)],  # summary
            [
                (
                    "evt-1",
                    "test-project",
                    "test-trace-id",
                    "span-1",
                    None,
                    "progress",
                    "Progress Event",
                    "worker",
                    "info",
                    "user",
                    "Step 1 complete",
                    {"step": 1},
                    timestamp,
                ),
                (
                    "evt-2",
                    "test-project",
                    "test-trace-id",
                    "span-2",
                    None,
                    "progress",
                    "Progress Event 2",
                    "worker",
                    "info",
                    "user",
                    "Step 2 complete",
                    {"step": 2},
                    timestamp + timedelta(seconds=10),
                ),
            ],
        ]

        result = get_events_with_filters(
            project_id="test-project", event_type="progress"
        )

        assert result["total"] == 2
        assert len(result["events"]) == 2
        assert all(e["event_type"] == "progress" for e in result["events"])

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_event_type_none_includes_all_types(
        self, mock_get_connection: MagicMock
    ):
        """Test that event_type=None includes all event types without filter."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [(5,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        result = get_events_with_filters(project_id="test-project", event_type=None)

        # Verify SQL does NOT contain event_type filter
        calls = mock_cursor.execute.call_args_list
        count_sql, count_params = calls[0].args
        assert "event_type = %s" not in count_sql
        assert len(count_params) == 1  # Only project_id


class TestGetEventsWithFiltersCombined:
    """Tests for get_events_with_filters() with combined after + event_type."""

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_after_and_event_type_combines_filters(
        self, mock_get_connection: MagicMock
    ):
        """Test that after + event_type filters combine correctly with AND."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        after_timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)

        mock_cursor.fetchone.side_effect = [(1,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        result = get_events_with_filters(
            project_id="test-project",
            after=after_timestamp,
            event_type="error",
        )

        # Verify both conditions are in SQL
        calls = mock_cursor.execute.call_args_list
        count_sql, count_params = calls[0].args
        assert "timestamp > %s" in count_sql
        assert "event_type = %s" in count_sql
        assert " AND " in count_sql
        assert after_timestamp in count_params
        assert "error" in count_params

    @patch("app.storage.events.get_connection")
    def test_get_events_with_filters_after_and_event_type_with_other_filters(
        self, mock_get_connection: MagicMock
    ):
        """Test that after + event_type work with other existing filters."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        after_timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)

        mock_cursor.fetchone.side_effect = [(1,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        result = get_events_with_filters(
            project_id="test-project",
            trace_id="test-trace-id",
            level="error",
            visibility="user",
            after=after_timestamp,
            event_type="state_change",
        )

        # Verify all conditions are in SQL
        calls = mock_cursor.execute.call_args_list
        count_sql, count_params = calls[0].args
        assert "project_id = %s" in count_sql
        assert "trace_id = %s" in count_sql
        assert "level = %s" in count_sql
        assert "visibility = %s" in count_sql
        assert "timestamp > %s" in count_sql
        assert "event_type = %s" in count_sql
        assert count_sql.count(" AND ") >= 5

        # Verify params order matches conditions
        assert "test-project" in count_params
        assert "test-trace-id" in count_params
        assert "error" in count_params
        assert "user" in count_params
        assert after_timestamp in count_params
        assert "state_change" in count_params


class TestGetEventsByTraceAfter:
    """Tests for get_events_by_trace() with after timestamp filter."""

    @patch("app.storage.events.get_connection")
    def test_get_events_by_trace_after_builds_correct_sql_condition(
        self, mock_get_connection: MagicMock
    ):
        """Test that after timestamp parameter builds correct SQL WHERE condition."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.return_value = []

        after_timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)
        result = get_events_by_trace(trace_id="test-trace-id", after=after_timestamp)

        # Verify execute was called with correct SQL and params
        calls = mock_cursor.execute.call_args_list
        assert len(calls) == 1

        sql, params = calls[0].args
        assert "trace_id = %s" in sql
        assert "timestamp > %s" in sql
        assert " AND " in sql
        assert "test-trace-id" in params
        assert after_timestamp in params
        assert result == []

    @patch("app.storage.events.get_connection")
    def test_get_events_by_trace_after_filters_correctly(
        self, mock_get_connection: MagicMock
    ):
        """Test that after filter returns only events after timestamp."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        after_timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)
        newer_timestamp = datetime(2026, 2, 14, 11, 0, 0, tzinfo=UTC)

        mock_cursor.fetchall.return_value = [
            (
                "evt-1",
                "test-project",
                "test-trace-id",
                "span-1",
                None,
                "log",
                "Event",
                "system",
                "info",
                "user",
                "Newer event",
                {"key": "value"},
                newer_timestamp,
            )
        ]

        result = get_events_by_trace(trace_id="test-trace-id", after=after_timestamp)

        assert len(result) == 1
        assert result[0]["timestamp"] == newer_timestamp
        assert result[0]["message"] == "Newer event"

    @patch("app.storage.events.get_connection")
    def test_get_events_by_trace_after_none_includes_all_events(
        self, mock_get_connection: MagicMock
    ):
        """Test that after=None includes all events without timestamp filter."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.return_value = []

        result = get_events_by_trace(trace_id="test-trace-id", after=None)

        # Verify SQL does NOT contain timestamp filter
        calls = mock_cursor.execute.call_args_list
        sql, params = calls[0].args
        assert "timestamp >" not in sql
        assert len(params) == 2  # trace_id + limit

    @patch("app.storage.events.get_connection")
    def test_get_events_by_trace_after_with_other_filters(
        self, mock_get_connection: MagicMock
    ):
        """Test that after works with visibility and level filters."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        after_timestamp = datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)

        mock_cursor.fetchall.return_value = []

        result = get_events_by_trace(
            trace_id="test-trace-id",
            visibility="user",
            level="error",
            after=after_timestamp,
        )

        # Verify all conditions are in SQL
        calls = mock_cursor.execute.call_args_list
        sql, params = calls[0].args
        assert "trace_id = %s" in sql
        assert "visibility = %s" in sql
        assert "level = %s" in sql
        assert "timestamp > %s" in sql
        assert sql.count(" AND ") >= 3

        assert "test-trace-id" in params
        assert "user" in params
        assert "error" in params
        assert after_timestamp in params


class TestEventsAPIEndpoints:
    """Tests for FastAPI endpoints accepting new query parameters."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create FastAPI test client."""
        from app.main import app

        return TestClient(app)

    @patch("app.storage.events.get_connection")
    def test_get_events_endpoint_accepts_after_parameter(
        self, mock_get_connection: MagicMock, client: TestClient
    ):
        """Test that /projects/{id}/events endpoint accepts after query param."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [(0,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        after_iso = "2026-02-14T10:00:00Z"
        response = client.get(
            f"/api/projects/test-project/events?after={after_iso}&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total" in data

    @patch("app.storage.events.get_connection")
    def test_get_events_endpoint_accepts_event_type_parameter(
        self, mock_get_connection: MagicMock, client: TestClient
    ):
        """Test that /projects/{id}/events endpoint accepts event_type query param."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [(0,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        response = client.get(
            "/api/projects/test-project/events?event_type=state_change&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total" in data

    @patch("app.storage.events.get_connection")
    def test_get_events_endpoint_accepts_combined_after_and_event_type(
        self, mock_get_connection: MagicMock, client: TestClient
    ):
        """Test that /projects/{id}/events accepts both after and event_type."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [(0,), None]
        mock_cursor.fetchall.side_effect = [[], []]

        after_iso = "2026-02-14T10:00:00Z"
        response = client.get(
            f"/api/projects/test-project/events?after={after_iso}&event_type=error&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total" in data

    @patch("app.storage.events.get_connection")
    def test_get_events_for_trace_endpoint_accepts_after_parameter(
        self, mock_get_connection: MagicMock, client: TestClient
    ):
        """Test that /projects/{id}/events/by-trace/{trace_id} accepts after param."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.return_value = []

        after_iso = "2026-02-14T10:00:00Z"
        response = client.get(
            f"/api/projects/test-project/events/by-trace/test-trace-id?after={after_iso}"
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "trace_id" in data
        assert data["trace_id"] == "test-trace-id"

    @patch("app.storage.events.get_connection")
    def test_get_events_for_trace_endpoint_after_with_other_params(
        self, mock_get_connection: MagicMock, client: TestClient
    ):
        """Test that by-trace endpoint accepts after with visibility and level."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.return_value = []

        after_iso = "2026-02-14T10:00:00Z"
        response = client.get(
            f"/api/projects/test-project/events/by-trace/test-trace-id"
            f"?after={after_iso}&visibility=user&level=error"
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "trace_id" in data
