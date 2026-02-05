"""Tests for Activity API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.main import app

client = TestClient(app)


class TestActivityFeed:
    """Tests for GET /api/activity."""

    def test_activity_feed_returns_events(self, mocker: MockerFixture) -> None:
        """Test that activity feed returns aggregated events."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = (
            [
                {
                    "type": "task",
                    "message": "Task completed: Fix bug",
                    "timestamp": "2026-01-17T12:00:00+00:00",
                    "project_id": "proj-123",
                    "metadata": {
                        "task_id": "task-abc",
                        "status": "completed",
                        "title": "Fix bug",
                    },
                },
                {
                    "type": "session",
                    "message": "Claude session completed (5 passed, 0 failed)",
                    "timestamp": "2026-01-17T11:00:00+00:00",
                    "project_id": "proj-123",
                    "metadata": {
                        "session_id": "sess-def",
                        "agent_type": "claude",
                        "status": "completed",
                        "tests_passed": 5,
                        "tests_failed": 0,
                    },
                },
            ],
            2,
        )

        response = client.get("/api/activity")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "has_more" in data

        assert len(data["items"]) == 2
        assert data["total"] == 2
        assert data["has_more"] is False

        # Check first event
        first = data["items"][0]
        assert first["type"] == "task"
        assert first["message"] == "Task completed: Fix bug"
        assert first["project_id"] == "proj-123"

    def test_activity_feed_pagination(self, mocker: MockerFixture) -> None:
        """Test pagination parameters are passed correctly."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = ([], 0)

        response = client.get("/api/activity?limit=10&offset=20")
        assert response.status_code == 200

        mock_get_activity.assert_called_once_with(
            project_id=None,
            limit=10,
            offset=20,
            event_types=None,
        )

    def test_activity_feed_project_filter(self, mocker: MockerFixture) -> None:
        """Test project_id filter is passed correctly."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = ([], 0)

        response = client.get("/api/activity?project_id=proj-123")
        assert response.status_code == 200

        mock_get_activity.assert_called_once_with(
            project_id="proj-123",
            limit=50,
            offset=0,
            event_types=None,
        )

    def test_activity_feed_type_filter(self, mocker: MockerFixture) -> None:
        """Test event type filter is parsed correctly."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = ([], 0)

        response = client.get("/api/activity?types=task,session")
        assert response.status_code == 200

        mock_get_activity.assert_called_once_with(
            project_id=None,
            limit=50,
            offset=0,
            event_types=["task", "session"],
        )

    def test_activity_feed_invalid_types_ignored(self, mocker: MockerFixture) -> None:
        """Test that invalid event types are filtered out."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = ([], 0)

        response = client.get("/api/activity?types=task,invalid,backup")
        assert response.status_code == 200

        mock_get_activity.assert_called_once_with(
            project_id=None,
            limit=50,
            offset=0,
            event_types=["task", "backup"],
        )

    def test_activity_feed_has_more_flag(self, mocker: MockerFixture) -> None:
        """Test has_more is True when more events exist."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = (
            [
                {
                    "type": "backup",
                    "message": "Manual backup completed",
                    "timestamp": "2026-01-17T10:00:00+00:00",
                    "project_id": "proj-123",
                    "metadata": {"backup_id": "bkp-xyz"},
                }
            ],
            10,  # Total is more than returned
        )

        response = client.get("/api/activity?limit=1")
        assert response.status_code == 200
        data = response.json()

        assert data["has_more"] is True


class TestActivityEventTypes:
    """Tests for different event type responses."""

    def test_task_event_format(self, mocker: MockerFixture) -> None:
        """Test task event has correct format."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = (
            [
                {
                    "type": "task",
                    "message": "Task blocked: Needs clarification",
                    "timestamp": "2026-01-17T12:00:00+00:00",
                    "project_id": "proj-123",
                    "metadata": {
                        "task_id": "task-abc",
                        "status": "blocked",
                        "title": "Needs clarification",
                    },
                }
            ],
            1,
        )

        response = client.get("/api/activity")
        assert response.status_code == 200
        event = response.json()["items"][0]

        assert event["type"] == "task"
        assert event["metadata"]["task_id"] == "task-abc"
        assert event["metadata"]["status"] == "blocked"

    def test_session_event_format(self, mocker: MockerFixture) -> None:
        """Test session event has correct format."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = (
            [
                {
                    "type": "session",
                    "message": "Gemini session failed",
                    "timestamp": "2026-01-17T12:00:00+00:00",
                    "project_id": "proj-456",
                    "metadata": {
                        "session_id": "sess-xyz",
                        "agent_type": "gemini",
                        "status": "failed",
                        "tests_passed": 3,
                        "tests_failed": 2,
                    },
                }
            ],
            1,
        )

        response = client.get("/api/activity")
        assert response.status_code == 200
        event = response.json()["items"][0]

        assert event["type"] == "session"
        assert event["metadata"]["agent_type"] == "gemini"
        assert event["metadata"]["tests_passed"] == 3
        assert event["metadata"]["tests_failed"] == 2

    def test_backup_event_format(self, mocker: MockerFixture) -> None:
        """Test backup event has correct format."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = (
            [
                {
                    "type": "backup",
                    "message": "Scheduled backup completed (15.2 MB)",
                    "timestamp": "2026-01-17T12:00:00+00:00",
                    "project_id": "proj-789",
                    "metadata": {
                        "backup_id": "bkp-123",
                        "backup_type": "scheduled",
                        "status": "completed",
                        "size_bytes": 15937024,
                    },
                }
            ],
            1,
        )

        response = client.get("/api/activity")
        assert response.status_code == 200
        event = response.json()["items"][0]

        assert event["type"] == "backup"
        assert event["metadata"]["backup_type"] == "scheduled"
        assert event["metadata"]["size_bytes"] == 15937024

    def test_git_event_format(self, mocker: MockerFixture) -> None:
        """Test git event has correct format."""
        mock_get_activity = mocker.patch("app.storage.activity.get_aggregated_activity")
        mock_get_activity.return_value = (
            [
                {
                    "type": "git",
                    "message": "Commit abc1234: Fix authentication bug",
                    "timestamp": "2026-01-17T12:00:00+00:00",
                    "project_id": "proj-123",
                    "metadata": {
                        "commit_sha": "abc1234567890",
                        "agent_type": "claude",
                        "notes": "Fix authentication bug",
                    },
                }
            ],
            1,
        )

        response = client.get("/api/activity")
        assert response.status_code == 200
        event = response.json()["items"][0]

        assert event["type"] == "git"
        assert event["metadata"]["commit_sha"] == "abc1234567890"
        assert event["metadata"]["agent_type"] == "claude"
