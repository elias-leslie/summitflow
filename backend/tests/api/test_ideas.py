"""Tests for Ideas API endpoints.

Covers submission, JWT extraction, retry limits, approval, and execution.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

from app.main import app
from fastapi.testclient import TestClient

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

    def test_cf_jwt_extraction(self):
        """Test email is correctly extracted from CF-Access-JWT-Assertion header."""
        from app.api.ideas import extract_email_from_cf_jwt

        jwt = make_jwt("test@example.com")
        email = extract_email_from_cf_jwt(jwt)
        assert email == "test@example.com"

    def test_cf_jwt_extraction_none(self):
        """Test None returned when no JWT provided."""
        from app.api.ideas import extract_email_from_cf_jwt

        assert extract_email_from_cf_jwt(None) is None

    def test_cf_jwt_extraction_invalid(self):
        """Test None returned for invalid JWT."""
        from app.api.ideas import extract_email_from_cf_jwt

        assert extract_email_from_cf_jwt("invalid.jwt") is None
        assert extract_email_from_cf_jwt("not-a-jwt") is None


class TestIdeaSubmission:
    """Tests for POST /api/projects/{id}/ideas."""

    @patch("app.api.ideas.get_connection")
    def test_submit_idea_returns_idea_id(self, mock_conn: MagicMock):
        """Test that submitting an idea returns an idea_id."""
        mock_cursor = MagicMock()
        # No JWT header → user_identifier = "anonymous" → skip user hourly check
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

    @patch("app.api.ideas.get_connection")
    def test_submit_idea_extracts_email(self, mock_conn: MagicMock):
        """Test that submitting with JWT extracts and stores email."""
        mock_cursor = MagicMock()
        # With JWT header → user_identifier = email → checks user hourly limit
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

    @patch("app.api.ideas.get_connection")
    def test_retry_limit(self, mock_conn: MagicMock):
        """Test retry is blocked after 3 attempts."""
        mock_cursor = MagicMock()
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

    @patch("app.storage.tasks.core.create_task")
    @patch("app.api.ideas.get_connection")
    def test_approve_creates_task(self, mock_conn: MagicMock, mock_create_task: MagicMock):
        """Test approving an idea creates a task."""
        mock_cursor = MagicMock()
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

    @patch("app.tasks.autonomous.ideas.process_crowdsourced_ideas")
    @patch("app.api.ideas.get_connection")
    @patch("app.api.ideas._last_execution", {})  # Clear throttle
    def test_immediate_execution(self, mock_conn: MagicMock, mock_process: MagicMock):
        """Test immediate execution triggers the processing task."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ["test-project"]  # Project exists
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        mock_task = MagicMock()
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

    @patch("app.services.idea_refiner.refine_idea")
    @patch("app.api.ideas.get_connection")
    def test_refine_idea_success(self, mock_conn: MagicMock, mock_refine: MagicMock):
        """Test successful refinement endpoint."""
        from app.services.idea_refiner import RefinementResult

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ["Make game faster", "pending_refinement"]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        mock_refine.return_value = RefinementResult(
            refined_text="Optimize rendering pipeline for smoother gameplay",
            category="enhancement",
            complexity="medium",
            feasibility_score=0.7,
            rejection_reason=None,
        )

        response = client.post("/api/projects/test-project/ideas/idea-abc123/refine")

        assert response.status_code == 200
        data = response.json()
        assert "refined_text" in data
        assert data["status"] == "refined"

    @patch("app.services.idea_refiner.refine_idea")
    @patch("app.api.ideas.get_connection")
    def test_refine_idea_rejected(self, mock_conn: MagicMock, mock_refine: MagicMock):
        """Test refinement that results in rejection."""
        from app.services.idea_refiner import RefinementResult

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ["Delete everything", "pending_refinement"]
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        mock_refine.return_value = RefinementResult(
            refined_text=None,
            category=None,
            complexity=None,
            feasibility_score=0.0,
            rejection_reason="Idea is not actionable or potentially harmful",
        )

        response = client.post("/api/projects/test-project/ideas/idea-abc123/refine")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert data["rejection_reason"] is not None
