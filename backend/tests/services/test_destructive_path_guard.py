from __future__ import annotations

from pathlib import Path

import pytest

from app.services.destructive_path_guard import (
    evaluate_destructive_paths,
    staged_destructive_paths,
)


def test_evaluate_destructive_paths_blocks_foreign_unknown_scope_same_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    decision = evaluate_destructive_paths(
        repo_root,
        ["docs/plans/vantage-rollout-plan.md"],
        [
            {
                "id": "sess-foreign",
                "current_branch": "main",
                "checkout_path": str(repo_root),
            }
        ],
        project_id="summitflow",
        current_session_id="sess-self",
        current_branch="main",
    )

    assert decision.blocked is True
    assert len(decision.conflicts) == 1
    assert decision.conflicts[0].reason == "unknown_scope"
    assert decision.conflicts[0].paths == ("docs/plans/vantage-rollout-plan.md",)


def test_evaluate_destructive_paths_blocks_foreign_scoped_path_same_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    decision = evaluate_destructive_paths(
        repo_root,
        ["docs/plans/vantage-rollout-plan.md", "README.md"],
        [
            {
                "id": "sess-foreign",
                "external_id": "task-123",
                "current_branch": "main",
                "checkout_path": str(repo_root),
                "observed_write_paths": ["docs/plans/vantage-rollout-plan.md"],
            }
        ],
        project_id="summitflow",
        current_session_id="sess-self",
        current_branch="main",
    )

    assert decision.blocked is True
    assert len(decision.conflicts) == 1
    assert decision.conflicts[0].reason == "scope_overlap"
    assert decision.conflicts[0].paths == ("docs/plans/vantage-rollout-plan.md",)


def test_evaluate_destructive_paths_uses_observed_scope_without_task_id(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    decision = evaluate_destructive_paths(
        repo_root,
        ["docs/plans/vantage-rollout-plan.md", "README.md"],
        [
            {
                "id": "sess-foreign",
                "current_branch": "main",
                "checkout_path": str(repo_root),
                "observed_write_paths": ["docs/plans/vantage-rollout-plan.md"],
                "scope_confidence": "observed_write",
            }
        ],
        project_id="summitflow",
        current_session_id="sess-self",
        current_branch="main",
    )

    assert decision.blocked is True
    assert len(decision.conflicts) == 1
    assert decision.conflicts[0].reason == "scope_overlap"
    assert decision.conflicts[0].paths == ("docs/plans/vantage-rollout-plan.md",)


def test_evaluate_destructive_paths_ignores_foreign_session_in_other_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    other_root = tmp_path / "other"
    repo_root.mkdir()
    other_root.mkdir()

    decision = evaluate_destructive_paths(
        repo_root,
        ["docs/plans/vantage-rollout-plan.md"],
        [
            {
                "id": "sess-foreign",
                "external_id": "task-123",
                "current_branch": "task-123/main",
                "checkout_path": str(other_root),
                "observed_write_paths": ["docs/plans/vantage-rollout-plan.md"],
            }
        ],
        project_id="summitflow",
        current_session_id="sess-self",
        current_branch="main",
    )

    assert decision.blocked is False
    assert decision.conflicts == ()


def test_evaluate_destructive_paths_allows_self_owned_unknown_scope_same_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    decision = evaluate_destructive_paths(
        repo_root,
        ["docs/plans/vantage-rollout-plan.md"],
        [
            {
                "id": "sess-self",
                "current_branch": "main",
                "checkout_path": str(repo_root),
            }
        ],
        project_id="summitflow",
        current_session_id="sess-self",
        current_branch="main",
    )

    assert decision.blocked is False
    assert decision.conflicts == ()


def test_staged_destructive_paths_returns_deleted_and_renamed_old_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess_args = []

    class _Result:
        stdout = (
            b"D\x00docs/plans/vantage-rollout-plan.md\x00"
            b"R100\x00docs/old.md\x00docs/new.md\x00"
        )

    def _fake_run(*args, **kwargs):
        subprocess_args.append((args, kwargs))
        return _Result()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.services.destructive_path_guard.subprocess.run", _fake_run)
    try:
        paths = staged_destructive_paths(repo_root)
    finally:
        monkeypatch.undo()

    assert paths == ["docs/old.md", "docs/plans/vantage-rollout-plan.md"]
    assert subprocess_args
