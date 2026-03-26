"""Tests for workspace cleanup summaries used by project pulse."""

from __future__ import annotations

from unittest.mock import patch

from app.services.workspace_status import build_project_cleanup_status


def test_build_project_cleanup_status_uses_canonical_cleanup_payload() -> None:
    payload = {
        "repositories": [
            {
                "project_id": "agent-hub",
                "path": "/srv/workspaces/projects/agent-hub",
                "active_worktrees": 2,
                "dirty_worktrees": 1,
                "stale_checkpoints": 0,
                "snapshot_residue": 1,
                "orphan_task_branches": 0,
                "prunable_task_branches": 0,
                "needs_merge_count": 0,
                "conflict_count": 0,
                "review_count": 2,
                "worktree_task_ids": ["task-1", "task-2"],
                "needs_cleanup": True,
            }
        ]
    }

    with patch(
        "app.services.workspace_status.build_cleanup_status_payload",
        return_value=payload,
    ) as mock_build:
        result = build_project_cleanup_status("agent-hub")

    assert result == {
        "project_id": "agent-hub",
        "path": "/srv/workspaces/projects/agent-hub",
        "active_worktrees": 2,
        "dirty_worktrees": 1,
        "stale_checkpoints": 0,
        "snapshot_residue": 1,
        "orphan_task_branches": 0,
        "prunable_task_branches": 0,
        "needs_merge_count": 0,
        "conflict_count": 0,
        "review_count": 2,
        "worktree_task_ids": ["task-1", "task-2"],
        "needs_cleanup": True,
    }
    mock_build.assert_called_once_with(False, project_id_override="agent-hub")


def test_build_project_cleanup_status_handles_missing_repo_entry() -> None:
    with patch(
        "app.services.workspace_status.build_cleanup_status_payload",
        return_value={"repositories": []},
    ):
        result = build_project_cleanup_status("missing-project")

    assert result == {
        "project_id": "missing-project",
        "path": None,
        "active_worktrees": 0,
        "dirty_worktrees": 0,
        "stale_checkpoints": 0,
        "snapshot_residue": 0,
        "orphan_task_branches": 0,
        "prunable_task_branches": 0,
        "needs_merge_count": 0,
        "conflict_count": 0,
        "review_count": 0,
        "worktree_task_ids": [],
        "needs_cleanup": False,
    }
