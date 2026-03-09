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
        from pathlib import Path

        from app.api.models.git_models import RepoStatus, RepoWorkspaceSummary

        mocker.patch("app.api.git.get_managed_repos", return_value=[Path("/test/repo")])
        mock_status = mocker.patch("app.api.git.get_repo_status")
        mock_status.return_value = RepoStatus(
            path="/test/repo",
            name="repo",
            branch="main",
            uncommitted=0,
            ahead=0,
            behind=0,
            state="clean",
            workspace_summary=RepoWorkspaceSummary(
                active_worktrees=1,
                branches_with_worktrees=1,
                task_branches=2,
                orphan_branches=1,
                prunable_branches=1,
                worktree_task_ids=["task-123"],
            ),
        )

        response = client.get("/api/git/status")
        assert response.status_code == 200
        data = response.json()
        assert "repositories" in data
        assert "total" in data
        assert isinstance(data["repositories"], list)
        assert data["repositories"][0]["workspace_summary"]["active_worktrees"] == 1


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


class TestFinalizeTaskEndpoint:
    """Tests for POST /api/git/tasks/{task_id}/finalize."""

    def test_finalize_rejects_blocked_task(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "app.api.git.task_store.get_task",
            return_value={"id": "task-1", "project_id": "agent-hub", "status": "blocked"},
        )

        response = client.post("/api/git/tasks/task-1/finalize")

        assert response.status_code == 400
        body = response.json()
        assert "not eligible for finalize" in str(body)

    def test_finalize_allows_completed_task(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "app.api.git.task_store.get_task",
            return_value={"id": "task-1", "project_id": "agent-hub", "status": "completed"},
        )
        merge = mocker.patch("app.api.git_helpers.endpoints.merge_and_cleanup_task_worktree")
        merge.return_value = {"task_id": "task-1", "status": "merged"}

        response = client.post("/api/git/tasks/task-1/finalize")

        assert response.status_code == 200
        assert response.json()["status"] == "merged"
        merge.assert_called_once_with("task-1", "agent-hub")


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
