"""Git service for task-related git operations.

This module provides a backward-compatible interface to git operations.
All functionality has been reorganized into submodules under app/services/git/.

For direct access to specific modules:
- app/services/git/branches.py - Branch operations
- app/services/git/commits.py - Commit operations
- app/services/git/pull_requests.py - PR operations
- app/services/git/utils.py - Utility operations
- app/services/git/worktrees.py - Worktree operations
"""

from .git.branches import checkout_branch, create_task_branch, get_current_branch, slugify
from .git.commits import capture_diff, commit_changes, get_current_commit, get_diff_stats
from .git.pull_requests import auto_create_pr, create_pull_request
from .git.utils import get_blob_shas, get_head_sha, push_branch, revert_to
from .git.worktrees import auto_claim_with_worktree, get_worktree_changes

__all__ = [
    "auto_claim_with_worktree",
    "auto_create_pr",
    "capture_diff",
    "checkout_branch",
    "commit_changes",
    "create_pull_request",
    "create_task_branch",
    "get_blob_shas",
    "get_current_branch",
    "get_current_commit",
    "get_diff_stats",
    "get_head_sha",
    "get_worktree_changes",
    "push_branch",
    "revert_to",
    "slugify",
]
