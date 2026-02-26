"""Git utility functions — public facade re-exporting from sub-modules.

All symbols importable from this module are preserved for backward compatibility.
Implementation is split across:
  - _git_core.py    — run_git, repo status, sync operations
  - _git_branches.py — branch, worktree helpers
  - _git_diff.py    — diff, commit history, snapshot helpers
"""

from __future__ import annotations

from ._git_branches import (
    extract_task_id_from_branch,
    get_all_branches,
    get_branch_commit_info,
    get_worktree_branches,
    get_worktree_info,
)
from ._git_core import (
    CONFIG_REPOS,
    WORKTREES_BASE_DIR,
    fetch_repository,
    get_managed_repos,
    get_repo_status,
    pull_repository,
    push_repository,
    run_git,
    sync_repository,
)
from ._git_diff import (
    get_diff_stats,
    get_recent_commits,
    get_task_diff,
    list_snapshots,
    revert_to_snapshot,
)

__all__ = [
    "CONFIG_REPOS",
    "WORKTREES_BASE_DIR",
    "extract_task_id_from_branch",
    "fetch_repository",
    "get_all_branches",
    "get_branch_commit_info",
    "get_diff_stats",
    "get_managed_repos",
    "get_recent_commits",
    "get_repo_status",
    "get_task_diff",
    "get_worktree_branches",
    "get_worktree_info",
    "list_snapshots",
    "pull_repository",
    "push_repository",
    "revert_to_snapshot",
    "run_git",
    "sync_repository",
]
