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

        from app.api.models.git_models import OrphanBranchSummary, RepoStatus, RepoWorkspaceSummary

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
                active_checkpoints=1,
                dirty_checkpoints=1,
                branches_with_checkpoints=1,
                task_branches=2,
                orphan_branches=1,
                prunable_branches=1,
                needs_cleanup=True,
                checkpoint_task_ids=["task-123"],
                orphan_details=[
                    OrphanBranchSummary(
                        branch_name="task-456/main",
                        task_id="task-456",
                        resolution="review",
                        task_status="running",
                        commits_ahead=2,
                        files_changed=4,
                    ),
                ],
            ),
        )

        response = client.get("/api/git/status")
        assert response.status_code == 200
        data = response.json()
        assert "repositories" in data
        assert "total" in data
        assert isinstance(data["repositories"], list)
        assert data["repositories"][0]["project_id"] == "summitflow"
        assert data["repositories"][0]["workspace_summary"]["active_checkpoints"] == 1
        assert data["repositories"][0]["workspace_summary"]["dirty_checkpoints"] == 1
        detail = data["repositories"][0]["workspace_summary"]["orphan_details"][0]
        assert detail["resolution"] == "review"
        assert detail["commits_ahead"] == 2


class TestGitCleanupStatus:
    """Tests for cleanup-status API surfaces."""

    def test_cleanup_status_returns_payload_and_compact(self, mocker: MockerFixture) -> None:
        payload = {
            "summary": {
                "repos": 1,
                "repos_needing_cleanup": 1,
                "active_checkpoints": 1,
                "dirty_checkpoints": 0,
                "stale_checkpoints": 0,
                "snapshot_residue": 0,
                "orphan_task_branches": 1,
                "prunable_task_branches": 0,
            },
            "repositories": [],
            "checkpoints": [],
            "total": 0,
        }
        mock_build = mocker.patch(
            "app.api.git.build_cleanup_status_payload",
            return_value=payload,
        )
        mock_render = mocker.patch(
            "app.api.git.render_cleanup_status_compact",
            return_value="CLEANUP[all]:repos=1 needs_cleanup=1",
        )

        response = client.get("/api/git/cleanup-status")

        assert response.status_code == 200
        data = response.json()
        assert data["payload"] == payload
        assert data["compact"] == "CLEANUP[all]:repos=1 needs_cleanup=1"
        mock_build.assert_called_once_with(True, project_id_override=None)
        mock_render.assert_called_once_with(payload, True)

    def test_project_cleanup_status_scopes_to_requested_project(self, mocker: MockerFixture) -> None:
        payload = {
            "summary": {
                "repos": 1,
                "repos_needing_cleanup": 0,
                "active_checkpoints": 0,
                "dirty_checkpoints": 0,
                "stale_checkpoints": 0,
                "snapshot_residue": 0,
                "orphan_task_branches": 0,
                "prunable_task_branches": 0,
            },
            "repositories": [{"project_id": "agent-hub"}],
            "checkpoints": [],
            "total": 0,
        }
        mock_build = mocker.patch(
            "app.api.git.build_cleanup_status_payload",
            return_value=payload,
        )
        mock_render = mocker.patch(
            "app.api.git.render_cleanup_status_compact",
            return_value="agent-hub clean",
        )

        response = client.get("/api/projects/agent-hub/git/cleanup-status")

        assert response.status_code == 200
        data = response.json()
        assert data["payload"] == payload
        assert data["compact"] == "agent-hub clean"
        mock_build.assert_called_once_with(False, project_id_override="agent-hub")
        mock_render.assert_called_once_with(payload, False)


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
        mock_enrich = mocker.patch("app.api.git.enrich_branch_cleanup_details")
        mock_branches.side_effect = [
            [
                BranchInfo(
                    name="main",
                    is_current=True,
                    has_checkpoint=False,
                    repo_name="alpha",
                    project_id="project-alpha",
                ),
            ],
            [
                BranchInfo(
                    name="task-123/main",
                    is_current=False,
                    has_checkpoint=True,
                    repo_name="beta",
                    project_id="project-beta",
                    task_id="task-123",
                ),
            ],
        ]
        mock_enrich.side_effect = lambda _repo_path, branches: branches

        response = client.get("/api/git/branches")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert {branch["repo_name"] for branch in body["branches"]} == {"alpha", "beta"}
        assert {branch["project_id"] for branch in body["branches"]} == {
            "project-alpha",
            "project-beta",
        }
        assert mock_enrich.call_count == 2


class TestProjectDashboard:
    """Tests for GET /api/git/projects/{project_id}/dashboard."""

    def test_project_dashboard_returns_branch_data(self, mocker: MockerFixture) -> None:
        from pathlib import Path

        from app.api.models.git_models import (
            BranchInfo,
            CheckpointInfo,
            CommitInfo,
            ConflictInfo,
            MergedTaskSummary,
            RecentMergesResponse,
            SnapshotInfo,
        )

        mocker.patch("app.api.git_helpers.endpoints.get_project_root_with_fallback", return_value=Path("/repos/custom-folder"))
        mocker.patch(
            "app.api.git_helpers.endpoints.collect_checkpoints",
            return_value=[
                CheckpointInfo(
                    task_id="task-1",
                    branch="task-1/main",
                    base_branch="main",
                    is_active=True,
                    project_id="project-123",
                ),
                CheckpointInfo(
                    task_id="task-2",
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
                    has_checkpoint=False,
                    repo_name="custom-folder",
                    project_id="project-123",
                    last_commit_short="abc1234",
                ),
            ],
        )
        enrich_branches = mocker.patch(
            "app.api.git_helpers.endpoints.enrich_branch_cleanup_details",
            side_effect=lambda _repo_path, branches: branches,
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
        assert body["checkpoints"][0]["project_id"] == "project-123"
        assert body["branches"][0]["project_id"] == "project-123"
        assert body["branches"][0]["repo_name"] == "custom-folder"
        assert body["conflicts"][0]["task_id"] == "task-9"
        enrich_branches.assert_called_once()
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
        merge = mocker.patch("app.api.git_helpers.endpoints.merge_and_cleanup_task_checkpoint")
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


class TestSmartSyncParsing:
    """Tests for smart-sync output parsing."""

    def test_parse_smart_sync_output_prefers_detail_for_errors(self) -> None:
        from app.api.git_helpers.endpoints import _parse_smart_sync_output

        payload = (
            '{"status":"FAILED","repos":[{"status":"ERROR","reason":"push_failed",'
            '"detail":"remote rejected the push","message":"Publish change","pushed":false}]}'
        )

        result = _parse_smart_sync_output(payload, "", 1)

        assert result["success"] is False
        assert result["reason"] == "push_failed"
        assert result["detail"] == "remote rejected the push"
        assert result["errors"] == ["remote rejected the push"]
        assert result["message"] == "Publish change"

    def test_parse_smart_sync_output_uses_stderr_when_json_missing_detail(self) -> None:
        from app.api.git_helpers.endpoints import _parse_smart_sync_output

        payload = '{"status":"FAILED","repos":[{"status":"ERROR","reason":"push_failed","pushed":false}]}'

        result = _parse_smart_sync_output(payload, "ssh: connect to host github.com timed out", 1)

        assert result["detail"] == "ssh: connect to host github.com timed out"
        assert result["errors"] == ["ssh: connect to host github.com timed out"]
        assert result["raw_output"].endswith("ssh: connect to host github.com timed out")

    def test_parse_smart_sync_output_preserves_workflow_metadata(self) -> None:
        from app.api.git_helpers.endpoints import _parse_smart_sync_output

        payload = (
            '{"status":"SUCCESS","repos":[{"status":"SUCCESS","message":"Publish change",'
            '"pushed":true,"workflow_summary":"CI=success@main#107 | release=success@v0.2.1#2",'
            '"workflow_hint":"gh run watch 107 --repo elias-leslie/a-term --exit-status",'
            '"workflow_runs":[{"workflow":"CI","state":"success","ref":"main","number":107,"url":"https://example.invalid/ci"}]}]}'
        )

        result = _parse_smart_sync_output(payload, "", 0)

        assert result["success"] is True
        assert result["workflow_summary"] == "CI=success@main#107 | release=success@v0.2.1#2"
        assert result["workflow_hint"] == "gh run watch 107 --repo elias-leslie/a-term --exit-status"
        assert result["workflow_runs"] == [
            {
                "workflow": "CI",
                "state": "success",
                "ref": "main",
                "number": 107,
                "url": "https://example.invalid/ci",
            }
        ]
