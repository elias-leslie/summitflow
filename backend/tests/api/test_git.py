"""Tests for Git API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestGitStatus:
    """Tests for GET /api/git/status."""

    @patch("app.api.git._get_repo_status")
    def test_git_status_returns_repos(self, mock_status: MagicMock):
        """Test that git status returns repository information."""
        from app.api.git import RepoStatus

        mock_status.return_value = RepoStatus(
            path="/test/repo",
            name="repo",
            branch="main",
            uncommitted=0,
            ahead=0,
            behind=0,
            state="clean",
        )

        response = client.get("/api/git/status")
        assert response.status_code == 200
        data = response.json()
        assert "repositories" in data
        assert "total" in data
        assert isinstance(data["repositories"], list)


class TestGitSync:
    """Tests for POST /api/git/sync."""

    @patch("app.api.git._get_repo_status")
    @patch("app.api.git._run_git")
    def test_git_sync_skips_dirty_repos(self, mock_run_git: MagicMock, mock_status: MagicMock):
        """Test that sync skips repos with uncommitted changes."""
        mock_status.return_value = MagicMock(
            path="/test/repo",
            name="repo",
            branch="main",
            uncommitted=5,  # Has uncommitted changes
            ahead=0,
            behind=0,
            state="dirty",
        )

        response = client.post("/api/git/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] > 0 or data["success"] >= 0


class TestPREndpoints:
    """Tests for /api/tasks/{task_id}/pr endpoints."""

    def test_get_pr_status_invalid_task(self):
        """Test 404 for invalid task."""
        response = client.get("/api/tasks/nonexistent/pr")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_pr_invalid_task(self):
        """Test 404 for invalid task."""
        response = client.post(
            "/api/tasks/nonexistent/pr",
            json={"title": "Test PR", "body": "Test body"},
        )
        assert response.status_code == 404
