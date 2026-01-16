"""Tests for git service agent workflow functions."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.git_service import (
    auto_claim_with_worktree,
    auto_create_pr,
    get_blob_shas,
    get_head_sha,
    get_worktree_changes,
)


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()

    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


class TestGetHeadSha:
    """Tests for get_head_sha function."""

    def test_returns_sha(self, temp_git_repo: Path) -> None:
        sha = get_head_sha(temp_git_repo)
        assert len(sha) == 40  # Full SHA
        assert all(c in "0123456789abcdef" for c in sha)

    def test_fails_on_non_repo(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError):
            get_head_sha(tmp_path)


class TestGetBlobShas:
    """Tests for get_blob_shas function."""

    def test_returns_shas_for_tracked_files(self, temp_git_repo: Path) -> None:
        result = get_blob_shas(temp_git_repo, ["README.md"])
        assert "README.md" in result
        assert len(result["README.md"]) == 40

    def test_skips_nonexistent_files(self, temp_git_repo: Path) -> None:
        result = get_blob_shas(temp_git_repo, ["nonexistent.txt"])
        assert "nonexistent.txt" not in result

    def test_handles_multiple_files(self, temp_git_repo: Path) -> None:
        (temp_git_repo / "other.txt").write_text("content")
        subprocess.run(
            ["git", "add", "other.txt"], cwd=temp_git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Add other"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
        )

        result = get_blob_shas(temp_git_repo, ["README.md", "other.txt"])
        assert len(result) == 2


class TestAutoClaimWithWorktree:
    """Tests for auto_claim_with_worktree function."""

    @patch("app.services.git_service.task_store")
    @patch("app.services.worktree_manager.WorktreeManager.create_worktree")
    def test_creates_worktree_and_updates_task(
        self,
        mock_create_worktree: MagicMock,
        mock_store: MagicMock,
        temp_git_repo: Path,
    ) -> None:
        mock_create_worktree.return_value = MagicMock(
            path=temp_git_repo / ".worktrees" / "test",
            branch="exec/task-123",
        )

        result = auto_claim_with_worktree("task-123", temp_git_repo, "project-1")

        assert "worktree_path" in result
        assert "branch_name" in result
        assert "base_sha" in result
        mock_store.update_task.assert_called_once()

    @patch("app.services.git_service.task_store")
    @patch("app.services.worktree_manager.WorktreeManager.create_worktree")
    def test_raises_on_worktree_error(
        self,
        mock_create_worktree: MagicMock,
        mock_store: MagicMock,
        temp_git_repo: Path,
    ) -> None:
        mock_create_worktree.side_effect = Exception("Worktree creation failed")

        with pytest.raises(RuntimeError) as exc_info:
            auto_claim_with_worktree("task-123", temp_git_repo, "project-1")

        assert "Failed to claim task" in str(exc_info.value)


class TestAutoCreatePr:
    """Tests for auto_create_pr function."""

    @patch("app.services.git_service.task_store")
    @patch("app.services.git_service.push_branch")
    @patch("subprocess.run")
    def test_creates_pr_successfully(
        self,
        mock_run: MagicMock,
        mock_push: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {
            "id": "task-123",
            "title": "Test Task",
            "description": "Description",
            "branch_name": "exec/task-123",
        }
        mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/1")

        result = auto_create_pr("task-123", Path("/tmp/repo"))

        assert result["pr_url"] == "https://github.com/org/repo/pull/1"
        assert result["branch_name"] == "exec/task-123"
        mock_store.update_task_status.assert_called_with("task-123", "ai_reviewing")

    @patch("app.services.git_service.task_store")
    def test_fails_on_missing_task(self, mock_store: MagicMock) -> None:
        mock_store.get_task.return_value = None

        with pytest.raises(RuntimeError) as exc_info:
            auto_create_pr("nonexistent", Path("/tmp/repo"))

        assert "not found" in str(exc_info.value)

    @patch("app.services.git_service.task_store")
    def test_fails_on_missing_branch(self, mock_store: MagicMock) -> None:
        mock_store.get_task.return_value = {"id": "task-123", "branch_name": None}

        with pytest.raises(RuntimeError) as exc_info:
            auto_create_pr("task-123", Path("/tmp/repo"))

        assert "has no branch_name" in str(exc_info.value)


class TestGetWorktreeChanges:
    """Tests for get_worktree_changes function."""

    def test_parses_empty_diff(self, temp_git_repo: Path) -> None:
        result = get_worktree_changes(temp_git_repo)
        assert result["files_changed"] == 0
        assert result["additions"] == 0
        assert result["deletions"] == 0

    def test_parses_changes(self, temp_git_repo: Path) -> None:
        (temp_git_repo / "new.txt").write_text("new content\n")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add new"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
        )

        result = get_worktree_changes(temp_git_repo)
        assert result["files_changed"] >= 1 or result["additions"] >= 1
