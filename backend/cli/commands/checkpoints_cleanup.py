"""Auto-cleanup logic for checkpoints command.

Handles cleanup of stale metadata, legacy SQL files, and orphaned branches.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..lib.worktree import get_worktree_info
from .checkpoints_branch_ops import (
    get_branch_unmerged_commits,
    get_orphaned_branches,
    get_task_branches,
)


def auto_cleanup_safe_items() -> tuple[int, int, int, list[dict]]:
    """Auto-cleanup clearly safe items.

    Returns (stale_meta, legacy_sql, cleaned_branches, branches_needing_review).

    Branches needing review have unmerged commits and require judgment.
    """
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    cleaned_meta = 0
    cleaned_sql = 0
    cleaned_branches = 0
    branches_needing_review: list[dict] = []

    # Find and clean stale metadata (no worktree AND no branch)
    if snapshots_dir.exists():
        for meta_file in snapshots_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
                task_id = meta.get("task_id", "")
                project_id = meta.get("project_id")

                # Check if worktree or branch exists
                worktree = get_worktree_info(task_id, project_id)
                branches = get_task_branches(task_id)

                if not worktree and not branches:
                    # Safe to delete - no worktree, no branch
                    meta_file.unlink()
                    cleaned_meta += 1
            except Exception:
                pass

        # Clean legacy SQL files
        for sql_file in snapshots_dir.glob("*.sql"):
            try:
                sql_file.unlink()
                cleaned_sql += 1
            except Exception:
                pass

    # Process orphaned branches - auto-delete only if 0 unmerged commits
    for branch in get_orphaned_branches():
        commits = get_branch_unmerged_commits(branch)

        if not commits:
            # 0 unmerged commits = safe to delete (already merged or identical to main)
            try:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                cleaned_branches += 1
            except subprocess.CalledProcessError:
                pass
        else:
            # Has unmerged commits - needs review
            branches_needing_review.append(
                {
                    "branch": branch,
                    "commits": commits,
                }
            )

    return (cleaned_meta, cleaned_sql, cleaned_branches, branches_needing_review)
