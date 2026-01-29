"""Tests for automation settings and budget enforcement.

Covers automation settings CRUD, budget limits, and scheduling.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestAutomationSettings:
    """Tests for GET/PUT /api/projects/{id}/settings/automation."""

    @patch("app.api.projects.automation.get_connection")
    def test_get_automation_settings(self, mock_conn: MagicMock):
        """Test fetching automation settings."""
        mock_cursor = MagicMock()
        # Return dict, not JSON string (psycopg parses JSONB)
        mock_cursor.fetchone.return_value = [
            {
                "schedule_preset": "nightly",
                "cron_expression": "0 3 * * *",
                "daily_budget_usd": 5.0,
                "primary_agent": "gemini",
                "secondary_agent": "claude",
                "enabled": False,
            }
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        response = client.get("/api/projects/test-project/settings/automation")

        assert response.status_code == 200
        data = response.json()
        assert data["schedule_preset"] == "nightly"
        assert data["daily_budget_usd"] == 5.0
        assert data["enabled"] is False

    @patch("app.api.projects.automation.get_connection")
    def test_update_automation_settings(self, mock_conn: MagicMock):
        """Test updating automation settings."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ["test-project"]  # Project exists
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        response = client.put(
            "/api/projects/test-project/settings/automation",
            json={
                "schedule_preset": "weekly",
                "cron_expression": "0 3 * * 0",
                "daily_budget_usd": 10.0,
                "primary_agent": "claude",
                "secondary_agent": "gemini",
                "enabled": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["schedule_preset"] == "weekly"
        assert data["daily_budget_usd"] == 10.0
        assert data["enabled"] is True

    @patch("app.api.projects.automation.get_connection")
    def test_budget_validation(self, mock_conn: MagicMock):
        """Test that negative budget is rejected."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ["test-project"]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        response = client.put(
            "/api/projects/test-project/settings/automation",
            json={
                "schedule_preset": "nightly",
                "cron_expression": "0 3 * * *",
                "daily_budget_usd": -5.0,  # Negative - should fail
                "primary_agent": "gemini",
                "secondary_agent": "claude",
                "enabled": True,
            },
        )

        assert response.status_code == 400


class TestCelerySchedule:
    """Tests for Celery beat schedule registration (ac-012)."""

    def test_celery_beat_schedule_exists(self):
        """Test that Celery beat schedule is configured."""
        from app.celery_app import celery_app

        # Check that the schedule exists
        beat_schedule = celery_app.conf.beat_schedule
        assert beat_schedule is not None

        # Check that schedules exist
        assert len(beat_schedule) > 0, "No Celery beat schedules configured"
