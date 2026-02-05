"""Tests for automation settings and budget enforcement.

Covers automation settings CRUD, budget limits, and scheduling.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.main import app

client = TestClient(app)


def _setup_mock_connection(mocker: MockerFixture, fetchone_return):
    """Helper to set up mock database connection."""
    mock_cursor = mocker.MagicMock()
    mock_cursor.fetchone.return_value = fetchone_return
    mock_conn = mocker.patch("app.api.projects.automation.get_connection")
    mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
        mock_cursor
    )
    return mock_cursor


class TestAutomationSettings:
    """Tests for GET/PUT /api/projects/{id}/settings/automation."""

    def test_get_automation_settings(self, mocker: MockerFixture):
        """Test fetching automation settings."""
        # Return dict, not JSON string (psycopg parses JSONB)
        _setup_mock_connection(
            mocker,
            [
                {
                    "schedule_preset": "nightly",
                    "cron_expression": "0 3 * * *",
                    "daily_budget_usd": 5.0,
                    "primary_agent": "gemini",
                    "secondary_agent": "claude",
                    "enabled": False,
                }
            ],
        )

        response = client.get("/api/projects/test-project/settings/automation")

        assert response.status_code == 200
        data = response.json()
        assert data["schedule_preset"] == "nightly"
        assert data["daily_budget_usd"] == 5.0
        assert data["enabled"] is False

    def test_update_automation_settings(self, mocker: MockerFixture):
        """Test updating automation settings."""
        _setup_mock_connection(mocker, ["test-project"])  # Project exists

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

    @pytest.mark.parametrize(
        "invalid_budget,expected_status",
        [
            (-5.0, 400),  # Negative budget
            (-0.01, 400),  # Small negative
        ],
    )
    def test_budget_validation(
        self, mocker: MockerFixture, invalid_budget: float, expected_status: int
    ):
        """Test that negative budget is rejected."""
        _setup_mock_connection(mocker, ["test-project"])

        response = client.put(
            "/api/projects/test-project/settings/automation",
            json={
                "schedule_preset": "nightly",
                "cron_expression": "0 3 * * *",
                "daily_budget_usd": invalid_budget,
                "primary_agent": "gemini",
                "secondary_agent": "claude",
                "enabled": True,
            },
        )

        assert response.status_code == expected_status


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
