"""Tests for WorktreeManager - git worktree isolation for autonomous execution."""

import subprocess
from pathlib import Path

import pytest
from app.services.worktree_manager import WorktreeManager


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()

    # Initialize git repo
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

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create main branch (in case default is master)
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


@pytest.fixture
def worktree_manager(temp_git_repo: Path, tmp_path: Path) -> WorktreeManager:
    """Create a WorktreeManager with custom base directory."""
    manager = WorktreeManager(temp_git_repo, base_branch="main")
    # Override base dir to use temp directory
    manager.WORKTREE_BASE_DIR = tmp_path / "worktrees"
    return manager


class TestWorktreeCreation:
    """Tests for worktree creation."""

    def test_create_worktree_success(
        self, worktree_manager: WorktreeManager, temp_git_repo: Path
    ) -> None:
        """Test creating a new worktree."""
        info = worktree_manager.create_worktree("test-project", "task-12345")

        assert info.path.exists()
        assert info.branch == "exec/task-12345"
        assert info.task_id == "task-12345"
        assert info.project_id == "test-project"
        assert info.base_branch == "main"

        # Verify worktree has the same content as main
        assert (info.path / "README.md").exists()

        # Cleanup
        worktree_manager.remove_worktree("test-project", "task-12345")

    def test_create_worktree_replaces_existing(self, worktree_manager: WorktreeManager) -> None:
        """Test that creating a worktree replaces existing one."""
        # Create first worktree
        info1 = worktree_manager.create_worktree("test-project", "task-12345")
        path1 = info1.path

        # Add a file to first worktree
        (path1 / "test.txt").write_text("first")

        # Create second worktree with same ID (should replace)
        info2 = worktree_manager.create_worktree("test-project", "task-12345")

        # Path should be the same
        assert info2.path == path1
        # But original file should be gone (fresh checkout)
        assert not (info2.path / "test.txt").exists()

        # Cleanup
        worktree_manager.remove_worktree("test-project", "task-12345")

    def test_worktree_path_structure(self, worktree_manager: WorktreeManager) -> None:
        """Test worktree path follows expected structure."""
        worktree_manager.create_worktree("my-project", "task-abc123")

        expected_path = worktree_manager.WORKTREE_BASE_DIR / "my-project" / "task-abc123"
        assert worktree_manager.get_worktree_path("my-project", "task-abc123") == expected_path

        # Cleanup
        worktree_manager.remove_worktree("my-project", "task-abc123")


class TestWorktreeIsolation:
    """Tests for verifying worktree isolation from main."""

    def test_changes_in_worktree_not_visible_in_main(
        self, worktree_manager: WorktreeManager, temp_git_repo: Path
    ) -> None:
        """Test that files written to worktree are not visible in main repo."""
        # Create worktree
        info = worktree_manager.create_worktree("test-project", "task-isolation")

        # Write a file in worktree
        test_file = info.path / "new_file.py"
        test_file.write_text("print('hello from worktree')")

        # Verify file exists in worktree
        assert test_file.exists()

        # Verify file does NOT exist in main repo
        assert not (temp_git_repo / "new_file.py").exists()

        # Cleanup
        worktree_manager.remove_worktree("test-project", "task-isolation")

    def test_commit_in_worktree_isolated(
        self, worktree_manager: WorktreeManager, temp_git_repo: Path
    ) -> None:
        """Test that commits in worktree don't affect main branch."""
        # Create worktree
        info = worktree_manager.create_worktree("test-project", "task-commit")

        # Write and commit a file in worktree
        test_file = info.path / "committed_file.py"
        test_file.write_text("print('committed')")

        worktree_manager.commit_in_worktree("test-project", "task-commit", "Add committed_file.py")

        # Verify main branch doesn't have the file
        result = subprocess.run(
            ["git", "ls-tree", "--name-only", "main"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )
        assert "committed_file.py" not in result.stdout

        # But worktree branch has it
        result = subprocess.run(
            ["git", "ls-tree", "--name-only", "exec/task-commit"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )
        assert "committed_file.py" in result.stdout

        # Cleanup
        worktree_manager.remove_worktree("test-project", "task-commit")


class TestMergeWorktree:
    """Tests for merging worktree changes back to main."""

    @pytest.mark.asyncio
    async def test_merge_success(
        self, worktree_manager: WorktreeManager, temp_git_repo: Path
    ) -> None:
        """Test successful merge of worktree changes to main."""
        # Create worktree with changes
        info = worktree_manager.create_worktree("test-project", "task-merge")
        (info.path / "merged_file.py").write_text("print('merged')")
        worktree_manager.commit_in_worktree("test-project", "task-merge", "Add merged_file.py")

        # Merge back to main
        success = await worktree_manager.merge_worktree(
            "test-project", "task-merge", delete_after=True
        )

        assert success

        # Verify file now exists on main
        result = subprocess.run(
            ["git", "ls-tree", "--name-only", "main"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )
        assert "merged_file.py" in result.stdout

        # Verify worktree is cleaned up
        assert not worktree_manager.worktree_exists("test-project", "task-merge")

    @pytest.mark.asyncio
    async def test_merge_conflict_aborts(
        self, worktree_manager: WorktreeManager, temp_git_repo: Path
    ) -> None:
        """Test that merge conflict aborts cleanly."""
        # Create worktree and modify README
        info = worktree_manager.create_worktree("test-project", "task-conflict")
        (info.path / "README.md").write_text("# Modified in worktree")
        worktree_manager.commit_in_worktree("test-project", "task-conflict", "Modify README")

        # Modify README on main (create conflict)
        (temp_git_repo / "README.md").write_text("# Modified on main")
        subprocess.run(
            ["git", "add", "README.md"], cwd=temp_git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Modify README on main"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
        )

        # Attempt merge (should fail)
        success = await worktree_manager.merge_worktree(
            "test-project", "task-conflict", delete_after=False
        )

        assert not success

        # Worktree should still exist
        assert worktree_manager.worktree_exists("test-project", "task-conflict")

        # Main should be clean (no merge in progress)
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == ""

        # Cleanup
        worktree_manager.remove_worktree("test-project", "task-conflict")


class TestConcurrency:
    """Tests for concurrent worktree operations."""

    def test_concurrent_worktrees_for_different_tasks(
        self, worktree_manager: WorktreeManager, temp_git_repo: Path
    ) -> None:
        """Test that multiple worktrees can exist for different tasks."""
        # Create three worktrees for different tasks
        info1 = worktree_manager.create_worktree("project-a", "task-1")
        info2 = worktree_manager.create_worktree("project-a", "task-2")
        info3 = worktree_manager.create_worktree("project-b", "task-3")

        # All should exist
        assert info1.path.exists()
        assert info2.path.exists()
        assert info3.path.exists()

        # All should have different paths
        assert info1.path != info2.path != info3.path

        # All should have different branches
        assert info1.branch != info2.branch != info3.branch

        # Cleanup
        worktree_manager.remove_worktree("project-a", "task-1")
        worktree_manager.remove_worktree("project-a", "task-2")
        worktree_manager.remove_worktree("project-b", "task-3")

    def test_list_active_worktrees(self, worktree_manager: WorktreeManager) -> None:
        """Test listing active worktrees."""
        # Create worktrees
        worktree_manager.create_worktree("project-x", "task-a")
        worktree_manager.create_worktree("project-x", "task-b")
        worktree_manager.create_worktree("project-y", "task-c")

        # List all
        all_worktrees = worktree_manager.list_active_worktrees()
        assert len(all_worktrees) == 3

        # List by project
        project_x = worktree_manager.list_active_worktrees("project-x")
        assert len(project_x) == 2
        assert all(w.project_id == "project-x" for w in project_x)

        project_y = worktree_manager.list_active_worktrees("project-y")
        assert len(project_y) == 1

        # Cleanup
        worktree_manager.remove_worktree("project-x", "task-a")
        worktree_manager.remove_worktree("project-x", "task-b")
        worktree_manager.remove_worktree("project-y", "task-c")


class TestCleanup:
    """Tests for worktree cleanup."""

    def test_remove_worktree(self, worktree_manager: WorktreeManager) -> None:
        """Test worktree removal."""
        info = worktree_manager.create_worktree("test-project", "task-remove")
        assert info.path.exists()

        worktree_manager.remove_worktree("test-project", "task-remove")

        assert not info.path.exists()
        assert not worktree_manager.worktree_exists("test-project", "task-remove")

    def test_cleanup_stale_worktrees(self, worktree_manager: WorktreeManager) -> None:
        """Test cleanup of stale worktrees by age."""
        # Create a worktree
        info = worktree_manager.create_worktree("test-project", "task-stale")

        # Cleanup with 0 hour max age (should remove everything)
        removed = worktree_manager.cleanup_stale_worktrees(max_age_hours=0)

        assert removed == 1
        assert not info.path.exists()


class TestGetOrCreate:
    """Tests for get_or_create_worktree."""

    def test_creates_if_not_exists(self, worktree_manager: WorktreeManager) -> None:
        """Test that get_or_create creates if worktree doesn't exist."""
        info = worktree_manager.get_or_create_worktree("test-project", "task-new")

        assert info.path.exists()
        assert info.task_id == "task-new"

        # Cleanup
        worktree_manager.remove_worktree("test-project", "task-new")

    def test_returns_existing(self, worktree_manager: WorktreeManager) -> None:
        """Test that get_or_create returns existing worktree."""
        # Create first
        info1 = worktree_manager.create_worktree("test-project", "task-existing")
        (info1.path / "marker.txt").write_text("exists")

        # Get or create
        info2 = worktree_manager.get_or_create_worktree("test-project", "task-existing")

        # Should be same worktree (marker file exists)
        assert (info2.path / "marker.txt").exists()
        assert info1.path == info2.path

        # Cleanup
        worktree_manager.remove_worktree("test-project", "task-existing")
