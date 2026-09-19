"""Tests for checkpoint metadata lookup across checkouts."""

from __future__ import annotations

import json
from pathlib import Path

from cli.lib.checkpoint_metadata import SnapshotMeta, load_snapshot_meta


def test_load_snapshot_meta_finds_global_project_checkpoint(tmp_path: Path, monkeypatch) -> None:
    """Checkpoint metadata should load from the global project-scoped directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    meta = SnapshotMeta(
        task_id="task-123",
        project_id="summitflow",
        base_branch="main",
        created_at="2026-03-07T06:00:00+00:00",
        claimed_by="tester",
    )
    global_meta_path = (
        tmp_path
        / ".local"
        / "share"
        / "st"
        / "checkpoints"
        / "summitflow"
        / "task-123.meta.json"
    )
    global_meta_path.parent.mkdir(parents=True, exist_ok=True)
    global_meta_path.write_text(json.dumps(meta.to_dict()), encoding="utf-8")

    loaded = load_snapshot_meta("task-123")

    assert loaded is not None
    assert loaded.project_id == "summitflow"
    assert loaded.base_branch == "main"
    assert loaded.claimed_by == "tester"


def test_snapshot_meta_from_dict_ignores_legacy_dirty_paths_field() -> None:
    """Legacy metadata written with main_repo_dirty_paths still loads."""
    legacy_payload = {
        "task_id": "task-789",
        "project_id": "summitflow",
        "base_branch": "main",
        "created_at": "2026-03-07T06:00:00+00:00",
        "claimed_by": "tester",
        "main_repo_dirty_paths": ["foo.py", "bar/baz.txt"],
    }

    loaded = SnapshotMeta.from_dict(legacy_payload)

    assert loaded.task_id == "task-789"
    assert loaded.to_dict() == {
        "task_id": "task-789",
        "project_id": "summitflow",
        "base_branch": "main",
        "created_at": "2026-03-07T06:00:00+00:00",
        "claimed_by": "tester",
    }


def test_snapshot_meta_preserves_base_commit() -> None:
    payload = {
        "task_id": "task-789",
        "project_id": "summitflow",
        "base_branch": "main",
        "created_at": "2026-03-07T06:00:00+00:00",
        "claimed_by": "tester",
        "base_commit": "abc123",
    }

    loaded = SnapshotMeta.from_dict(payload)

    assert loaded.base_commit == "abc123"
    assert loaded.to_dict()["base_commit"] == "abc123"


def test_paused_checkpoint_is_retained_but_not_active(monkeypatch) -> None:
    from cli.lib import checkpoint

    meta = SnapshotMeta("task-paused", "agent-hub", "main", "2026-05-22T00:00:00+00:00", "tester")
    monkeypatch.setattr(checkpoint, "_iter_checkpoint_meta", lambda _project: [meta])
    monkeypatch.setattr(checkpoint, "_task_status", lambda _task: "paused")

    assert checkpoint.get_active_checkpoints("agent-hub") == []
    assert checkpoint.get_stale_checkpoints("agent-hub") == []


def test_terminal_checkpoint_remains_eligible_for_metadata_cleanup(monkeypatch) -> None:
    from cli.lib import checkpoint

    meta = SnapshotMeta("task-completed", "agent-hub", "main", "2026-05-22T00:00:00+00:00", "tester")
    monkeypatch.setattr(checkpoint, "_iter_checkpoint_meta", lambda _project: [meta])
    monkeypatch.setattr(checkpoint, "_task_status", lambda _task: "completed")

    assert checkpoint.get_active_checkpoints("agent-hub") == []
    assert checkpoint.get_stale_checkpoints("agent-hub") == [meta]
