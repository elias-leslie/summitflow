"""Git operations module.

Re-exports all git functionality from submodules for backward compatibility.
"""

from .branches import checkout_branch, create_task_branch, get_current_branch, slugify
from .commits import capture_diff, commit_changes, get_current_commit, get_diff_stats
from .utils import get_blob_shas, get_head_sha, push_branch, revert_to

__all__ = [
    "capture_diff",
    "checkout_branch",
    "commit_changes",
    "create_task_branch",
    "get_blob_shas",
    "get_current_branch",
    "get_current_commit",
    "get_diff_stats",
    "get_head_sha",
    "push_branch",
    "revert_to",
    "slugify",
]
