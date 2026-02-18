"""Auto-cleanup logic for checkpoints command."""

from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path
from typing import Any

from ..lib.worktree import get_worktree_info
from .checkpoints_branch_ops import (
    get_branch_unmerged_commits,
    get_orphaned_branches,
    get_task_branches,
)


def _is_stale_meta(meta_file: Path) -> bool:
    """Return True if the meta file has no associated worktree or branch."""
    meta = json.loads(meta_file.read_text())
    task_id = meta.get("task_id", "")
    project_id = meta.get("project_id")
    return not get_worktree_info(task_id, project_id) and not get_task_branches(task_id)


def _cleanup_snapshots_dir(snapshots_dir: Path) -> tuple[int, int]:
    """Delete stale meta files and legacy SQL files. Returns (cleaned_meta, cleaned_sql)."""
    cleaned_meta = 0
    cleaned_sql = 0
    for meta_file in snapshots_dir.glob("*.meta.json"):
        try:
            if _is_stale_meta(meta_file):
                meta_file.unlink()
                cleaned_meta += 1
        except Exception:
            pass
    for sql_file in snapshots_dir.glob("*.sql"):
        try:
            sql_file.unlink()
            cleaned_sql += 1
        except Exception:
            pass
    return cleaned_meta, cleaned_sql


def _process_orphaned_branch(branch: str) -> dict[str, Any] | None:
    """Delete branch if fully merged; return review info if it has unmerged commits."""
    unmerged_commits = get_branch_unmerged_commits(branch)
    if not unmerged_commits:
        with contextlib.suppress(subprocess.CalledProcessError):
            subprocess.run(["git", "branch", "-D", branch], check=True, capture_output=True, text=True)
        return None
    return {"branch": branch, "commits": unmerged_commits}


def auto_cleanup_safe_items() -> tuple[int, int, int, list[dict[str, Any]]]:
    """Auto-cleanup clearly safe items.

    Returns (stale_meta, legacy_sql, cleaned_branches, branches_needing_review).
    Branches needing review have unmerged commits and require judgment.
    """
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    cleaned_meta, cleaned_sql = 0, 0
    if snapshots_dir.exists():
        cleaned_meta, cleaned_sql = _cleanup_snapshots_dir(snapshots_dir)

    cleaned_branches = 0
    branches_needing_review: list[dict[str, Any]] = []
    for branch in get_orphaned_branches():
        review_info = _process_orphaned_branch(branch)
        if review_info is None:
            cleaned_branches += 1
        else:
            branches_needing_review.append(review_info)

    return (cleaned_meta, cleaned_sql, cleaned_branches, branches_needing_review)
