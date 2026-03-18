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
            project_id="summitflow",
            branch="main",
            uncommitted=0,
            ahead=0,
            behind=0,
            state="clean",
            workspace_summary=RepoWorkspaceSummary(
                active_worktrees=1,
                dirty_worktrees=1,
                branches_with_worktrees=1,
                task_branches=2,
                orphan_branches=1,
                prunable_branches=1,
                needs_cleanup=True,
                worktree_task_ids=["task-123"],
            ),
        )

        response = client.get("/api/git/status")
        assert response.status_code == 200
        data = response.json()
        assert "repositories" in data
        assert "total" in data
        assert isinstance(data["repositories"], list)
        assert data["repositories"][0]["project_id"] == "summitflow"
        assert data["repositories"][0]["workspace_summary"]["active_worktrees"] == 1
        assert data["repositories"][0]["workspace_summary"]["dirty_worktrees"] == 1


class TestGitBranches:
    """Tests for GET /api/git/branches."""

    def test_git_branches_aggregates_managed_repos(self, mocker: MockerFixture) -> None:
        from pathlib import Path

        from app.api.models.git_models import BranchInfo

        mocker.patch(
            "app.api.git.get_managed_repos",
            return_value=[Path("/repos/alpha"), Path("/repos/beta")],
        )
        mock_branches = mocker.patch("app.api.git.get_all_branches")
        mock_branches.side_effect = [
            [
                BranchInfo(
                    name="main",
                    is_current=True,
                    has_worktree=False,
                    repo_name="alpha",
                    project_id="project-alpha",
                ),
            ],
            [
                BranchInfo(
                    name="task-123/main",
                    is_current=False,
                    has_worktree=True,
                    repo_name="beta",
                    project_id="project-beta",
                    task_id="task-123",
                ),
            ],
        ]

        response = client.get("/api/git/branches")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert {branch["repo_name"] for branch in body["branches"]} == {"alpha", "beta"}
        assert {branch["project_id"] for branch in body["branches"]} == {
            "project-alpha",
            "project-beta",
        }


class TestProjectDashboard:
    """Tests for GET /api/git/projects/{project_id}/dashboard."""

    def test_project_dashboard_returns_branch_data(self, mocker: MockerFixture) -> None:
        from pathlib import Path

        from app.api.models.git_models import (
            BranchInfo,
            CommitInfo,
            ConflictInfo,
            MergedTaskSummary,
            RecentMergesResponse,
            SnapshotInfo,
            WorktreeInfo,
        )

        mocker.patch("app.api.git_helpers.endpoints.get_project_root_with_fallback", return_value=Path("/repos/custom-folder"))
        mocker.patch(
            "app.api.git_helpers.endpoints.collect_worktrees",
            return_value=[
                WorktreeInfo(
                    task_id="task-1",
                    path="/wt/task-1",
                    branch="task-1/main",
                    base_branch="main",
                    is_active=True,
                    project_id="project-123",
                ),
                WorktreeInfo(
                    task_id="task-2",
                    path="/wt/task-2",
                    branch="task-2/main",
                    base_branch="main",
                    is_active=True,
                    project_id="other-project",
                ),
            ],
        )
        mocker.patch(
            "app.api.git_helpers.endpoints.get_all_branches",
            return_value=[
                BranchInfo(
                    name="main",
                    is_current=True,
                    has_worktree=False,
                    repo_name="custom-folder",
                    project_id="project-123",
                    last_commit_short="abc1234",
                ),
            ],
        )
        mocker.patch(
            "app.api.git_helpers.endpoints.build_recent_merges_response",
            return_value=RecentMergesResponse(
                merges=[
                    MergedTaskSummary(
                        task_id="task-1",
                        task_title="Ship feature",
                        project_id="project-123",
                        merged_at="2026-03-17T10:00:00Z",
                        files_changed=3,
                        additions=12,
                        deletions=4,
                    ),
                ],
                count=1,
            ),
        )
        mocker.patch(
            "app.api.git_helpers.endpoints.get_recent_commits",
            return_value=[
                CommitInfo(
                    sha="abc123456789",
                    short_sha="abc1234",
                    message="Fix issue",
                    author_name="Dev",
                    author_email="dev@example.com",
                    date="2026-03-17T11:00:00Z",
                    repo_name="custom-folder",
                    files_changed=2,
                    insertions=10,
                    deletions=1,
                ),
            ],
        )
        mocker.patch(
            "app.api.git_helpers.endpoints.list_snapshots",
            return_value=[
                SnapshotInfo(
                    task_id="task-1",
                    task_title="",
                    sha="def123456789",
                    short_sha="def1234",
                    created_at="2026-03-17T09:00:00Z",
                    project_id="project-123",
                    repo_name="custom-folder",
                    is_current=False,
                    commits_ahead=1,
                ),
            ],
        )
        enrich_snapshots = mocker.patch("app.api.git_helpers.endpoints.enrich_snapshots")
        mocker.patch(
            "app.api.git_helpers.endpoints.build_conflicts_response",
            return_value=[
                ConflictInfo(
                    task_id="task-9",
                    task_title="Resolve merge",
                    project_id="project-123",
                    conflicting_files=["backend/app/api/git.py"],
                    task_branch="task-9/main",
                    base_branch="main",
                    detected_at="2026-03-17T12:00:00Z",
                ),
            ],
        )

        response = client.get("/api/git/projects/project-123/dashboard")

        assert response.status_code == 200
        body = response.json()
        assert body["worktrees"][0]["project_id"] == "project-123"
        assert body["branches"][0]["project_id"] == "project-123"
        assert body["branches"][0]["repo_name"] == "custom-folder"
        assert body["conflicts"][0]["task_id"] == "task-9"
        enrich_snapshots.assert_called_once()


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
        mocker.patch(
            "app.storage.subtasks.get_subtasks_for_task",
            return_value=[{"subtask_id": "1.1", "passes": True}],
        )
        merge = mocker.patch("app.api.git_helpers.endpoints.merge_and_cleanup_task_worktree")
        merge.return_value = {"task_id": "task-1", "status": "merged"}

        response = client.post("/api/git/tasks/task-1/finalize")

        assert response.status_code == 200
        assert response.json()["status"] == "merged"
        merge.assert_called_once_with("task-1", "agent-hub")

    def test_finalize_rejects_failed_subtasks(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "app.api.git.task_store.get_task",
            return_value={"id": "task-1", "project_id": "agent-hub", "status": "completed"},
        )
        mocker.patch(
            "app.storage.subtasks.get_subtasks_for_task",
            return_value=[
                {"subtask_id": "1.1", "passes": True},
                {"subtask_id": "1.2", "passes": False},
            ],
        )

        response = client.post("/api/git/tasks/task-1/finalize")

        assert response.status_code == 400
        body = response.json()
        assert "1.2" in str(body)


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
