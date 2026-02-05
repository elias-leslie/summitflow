"""Tests for Git API endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.main import app

client = TestClient(app)


class TestGitStatus:
    """Tests for GET /api/git/status."""

    def test_git_status_returns_repos(self, mocker: MockerFixture) -> None:
        """Test that git status returns repository information."""
        from app.api.models.git_models import RepoStatus

        mock_status = mocker.patch("app.api.git.get_repo_status")
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

    def test_git_sync_skips_dirty_repos(self, mocker: MockerFixture) -> None:
        """Test that sync skips repos with uncommitted changes."""
        from app.api.models.git_models import SyncResult

        mock_get_repos = mocker.patch("app.api.git.get_managed_repos")
        mock_sync = mocker.patch("app.api.git.sync_repository")
        mock_get_repos.return_value = ["/test/repo"]

        mock_sync.return_value = SyncResult(
            path="/test/repo",
            name="repo",
            branch="main",
            status="skipped",
            reason="Skipped due to uncommitted changes",
        )

        response = client.post("/api/git/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] > 0
        assert data["failed"] == 0
        assert data["success"] == 0


class TestPREndpoints:
    """Tests for /api/tasks/{task_id}/pr endpoints."""

    @pytest.mark.parametrize(
        "method,endpoint,json_data",
        [
            ("get", "/api/tasks/nonexistent/pr", None),
            ("post", "/api/tasks/nonexistent/pr", {"title": "Test PR", "body": "Test body"}),
        ],
        ids=["get_pr_status", "create_pr"],
    )
    def test_pr_invalid_task_returns_404(
        self, method: str, endpoint: str, json_data: dict[str, Any] | None
    ) -> None:
        """Test 404 for invalid task on PR endpoints."""
        if method == "get":
            response = client.get(endpoint)
        else:
            response = client.post(endpoint, json=json_data)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
