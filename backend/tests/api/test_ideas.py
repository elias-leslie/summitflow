"""Tests for Ideas API endpoints.

Covers submission, JWT extraction, retry limits, approval, and execution.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.main import app

client = TestClient(app)


def make_jwt(email: str) -> str:
    """Create a mock CF Access JWT with an email claim."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    payload_data = {"email": email, "exp": 9999999999}
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"fake_signature").decode().rstrip("=")
    return f"{header}.{payload}.{signature}"


class TestCFJWTExtraction:
    """Tests for Cloudflare JWT email extraction (ac-009)."""

    def test_cf_jwt_extraction(self) -> None:
        """Test email is correctly extracted from CF-Access-JWT-Assertion header."""
        from app.services.ideas_helpers import extract_email_from_cf_jwt

        jwt = make_jwt("test@example.com")
        email = extract_email_from_cf_jwt(jwt)
        assert email == "test@example.com"

    def test_cf_jwt_extraction_none(self) -> None:
        """Test None returned when no JWT provided."""
        from app.services.ideas_helpers import extract_email_from_cf_jwt

        assert extract_email_from_cf_jwt(None) is None

    @pytest.mark.parametrize(
        "invalid_jwt",
        [
            "invalid.jwt",
            "not-a-jwt",
        ],
        ids=["invalid_format", "no_dots"],
    )
    def test_cf_jwt_extraction_invalid(self, invalid_jwt: str) -> None:
        """Test None returned for invalid JWT."""
        from app.services.ideas_helpers import extract_email_from_cf_jwt

        assert extract_email_from_cf_jwt(invalid_jwt) is None


class TestIdeaSubmission:
    """Tests for POST /api/projects/{id}/ideas."""

    def test_submit_idea_returns_idea_id(self, mocker: MockerFixture) -> None:
        """Test that submitting an idea returns an idea_id."""
        mocker.patch("asyncio.create_task")
        mock_conn = mocker.patch("app.storage.ideas_repository.get_connection")
        mock_cursor = mocker.MagicMock()
        # No JWT header -> user_identifier = "anonymous" -> skip user hourly check
        mock_cursor.fetchone.side_effect = [
            [0],  # Rate limit: daily refinements count
            [{"daily_budget_usd": 5.0}],  # Rate limit: project automation_settings
            [1],  # Project exists
            ["idea-abc123"],  # Created idea ID
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        response = client.post(
            "/api/projects/test-project/ideas",
            json={"raw_text": "Make the game faster"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "idea_id" in data
        assert data["status"] == "pending_refinement"

    def test_submit_idea_extracts_email(self, mocker: MockerFixture) -> None:
        """Test that submitting with JWT extracts and stores email."""
        mocker.patch("asyncio.create_task")
        mock_conn = mocker.patch("app.storage.ideas_repository.get_connection")
        mock_cursor = mocker.MagicMock()
        # With JWT header -> user_identifier = email -> checks user hourly limit
        mock_cursor.fetchone.side_effect = [
            [0],  # Rate limit: user hourly count
            [0],  # Rate limit: daily refinements count
            [{"daily_budget_usd": 5.0}],  # Rate limit: project automation_settings
            [1],  # Project exists
            ["idea-abc123"],  # Created idea ID
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        jwt = make_jwt("player@game.com")
        response = client.post(
            "/api/projects/test-project/ideas",
            json={"raw_text": "Add more levels"},
            headers={"CF-Access-JWT-Assertion": jwt},
        )

        assert response.status_code == 201
        # Verify email was passed to the INSERT
        insert_call = mock_cursor.execute.call_args_list[-1]
        args = insert_call[0][1]
        assert "player@game.com" in args


class TestRetryLimit:
    """Tests for retry limit enforcement (ac-003)."""

    def test_retry_limit(self, mocker: MockerFixture) -> None:
        """Test retry is blocked after 3 attempts."""
        mock_conn = mocker.patch("app.storage.ideas_repository.get_connection")
        mock_cursor = mocker.MagicMock()
        # Return idea with retry_count=3
        mock_cursor.fetchone.return_value = [
            "Make game better",  # raw_text
            3,  # retry_count - at limit
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        response = client.post(
            "/api/projects/test-project/ideas/idea-abc123/retry",
            json={"additional_context": "please try again"},
        )

        assert response.status_code == 429


class TestIdeaApproval:
    """Tests for POST /api/projects/{id}/ideas/{id}/approve."""

    def test_approve_creates_task(self, mocker: MockerFixture) -> None:
        """Test approving an idea creates a task."""
        mock_conn = mocker.patch("app.storage.ideas_repository.get_connection")
        mock_create_task = mocker.patch("app.api.ideas.create_task")
        mock_cursor = mocker.MagicMock()
        mock_cursor.fetchone.return_value = [
            "Add jump animation",  # refined_text
            "feature",  # category
            "simple",  # complexity
            "refined",  # status
            "player@game.com",  # user_email
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        mock_create_task.return_value = {"id": "task-xyz123"}

        response = client.post("/api/projects/test-project/ideas/idea-abc123/approve")

        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "approved"
        mock_create_task.assert_called_once()


class TestImmediateExecution:
    """Tests for POST /api/projects/{id}/ideas/execute-now (ac-011)."""

    def test_immediate_execution(self, mocker: MockerFixture) -> None:
        """Test immediate execution triggers the processing task."""
        mock_conn = mocker.patch("app.storage.ideas_repository.get_connection")
        mock_process = mocker.patch("app.tasks.autonomous.ideas.process_crowdsourced_ideas")
        mocker.patch("app.api.ideas._last_execution", {})  # Clear throttle
        mock_cursor = mocker.MagicMock()
        mock_cursor.fetchone.return_value = ["test-project"]  # Project exists
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        mock_task = mocker.MagicMock()
        mock_task.id = "celery-task-123"
        mock_process.delay.return_value = mock_task

        response = client.post("/api/projects/test-project/ideas/execute-now")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dispatched"
        assert "task_id" in data
        mock_process.delay.assert_called_once_with("test-project")


class TestRefinementFlow:
    """Tests for idea refinement and status transitions."""

    @pytest.mark.parametrize(
        "raw_text,refined_text,category,complexity,feasibility,rejection_reason,expected_status",
        [
            (
                "Make game faster",
                "Optimize rendering pipeline for smoother gameplay",
                "enhancement",
                "medium",
                0.7,
                None,
                "refined",
            ),
            (
                "Delete everything",
                "",  # Empty string instead of None for rejected case
                "",
                "",
                0.0,
                "Idea is not actionable or potentially harmful",
                "rejected",
            ),
        ],
        ids=["success", "rejected"],
    )
    def test_refine_idea(
        self,
        mocker: MockerFixture,
        raw_text: str,
        refined_text: str,
        category: str,
        complexity: str,
        feasibility: float,
        rejection_reason: str | None,
        expected_status: str,
    ) -> None:
        """Test idea refinement with success and rejection cases."""
        from app.services.idea_refiner import RefinementResult

        mock_conn = mocker.patch("app.storage.ideas_repository.get_connection")
        mock_refine = mocker.patch("app.services.idea_refiner.refine_idea")
        mocker.patch("app.services.idea_refiner.update_idea_with_refinement")
        mock_cursor = mocker.MagicMock()
        mock_cursor.fetchone.return_value = [raw_text, "pending_refinement"]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        mock_refine.return_value = RefinementResult(
            refined_text=refined_text,
            category=category,
            complexity=complexity,
            feasibility_score=feasibility,
            rejection_reason=rejection_reason,
        )

        response = client.post("/api/projects/test-project/ideas/idea-abc123/refine")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == expected_status
        if expected_status == "refined":
            assert "refined_text" in data
        else:
            assert data["rejection_reason"] is not None
