"""Unit tests for lane-local Node workspace preparation."""

from __future__ import annotations

import json
from pathlib import Path


def _write_package_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n  - frontend\n  - packages/*\n",
        encoding="utf-8",
    )


def test_prepare_node_workspace_replaces_escaped_symlinks_and_materializes_file_deps(tmp_path: Path) -> None:
    from app.worktree_node_workspace import prepare_node_workspace

    main_root = tmp_path / "projects" / "agent-hub"
    lane_root = tmp_path / "lanes" / "agent-hub" / "task-1"
    _write_workspace(main_root)
    _write_workspace(lane_root)

    _write_package_json(
        main_root / "frontend" / "package.json",
        {"dependencies": {"notes-ui": "file:../../summitflow/packages/notes-ui"}},
    )
    _write_package_json(main_root / "packages" / "chat-ui" / "package.json", {"name": "chat-ui"})
    _write_package_json(
        lane_root / "frontend" / "package.json",
        {"dependencies": {"notes-ui": "file:../../summitflow/packages/notes-ui"}},
    )
    _write_package_json(lane_root / "packages" / "chat-ui" / "package.json", {"name": "chat-ui"})

    (main_root / "node_modules").mkdir(parents=True)
    source_dep = tmp_path / "projects" / "summitflow" / "packages" / "notes-ui"
    source_dep.mkdir(parents=True)

    (lane_root / "node_modules").symlink_to(main_root / "node_modules")
    (lane_root / "frontend" / "node_modules").symlink_to(main_root / "frontend" / "node_modules")
    (lane_root / "packages" / "chat-ui" / "node_modules").symlink_to(
        main_root / "packages" / "chat-ui" / "node_modules"
    )

    result = prepare_node_workspace(lane_root, main_root, cwd="frontend")

    assert result.needs_install is True
    assert result.workspace_root == str(lane_root)
    assert sorted(result.removed_node_modules_symlinks) == [
        "frontend/node_modules",
        "node_modules",
        "packages/chat-ui/node_modules",
    ]
    assert result.materialized_file_dependency_links == [
        str(tmp_path / "lanes" / "agent-hub" / "summitflow" / "packages" / "notes-ui")
    ]
    assert not (lane_root / "node_modules").exists()
    assert not (lane_root / "frontend" / "node_modules").exists()
    assert not (lane_root / "packages" / "chat-ui" / "node_modules").exists()
    lane_dep = tmp_path / "lanes" / "agent-hub" / "summitflow" / "packages" / "notes-ui"
    assert lane_dep.is_symlink()
    assert lane_dep.resolve() == source_dep.resolve()


def test_prepare_node_workspace_keeps_internal_symlinks_when_workspace_is_clean(tmp_path: Path) -> None:
    from app.worktree_node_workspace import prepare_node_workspace

    main_root = tmp_path / "projects" / "agent-hub"
    lane_root = tmp_path / "lanes" / "agent-hub" / "task-1"
    _write_workspace(main_root)
    _write_workspace(lane_root)

    _write_package_json(main_root / "frontend" / "package.json", {"name": "frontend"})
    _write_package_json(lane_root / "frontend" / "package.json", {"name": "frontend"})

    (lane_root / "node_modules").mkdir(parents=True)
    internal_store = lane_root / ".deps"
    internal_store.mkdir(parents=True)
    (lane_root / "frontend" / "node_modules").symlink_to(internal_store)

    result = prepare_node_workspace(lane_root, main_root, cwd="frontend")

    assert result.needs_install is False
    assert result.removed_node_modules_symlinks == []
    assert result.materialized_file_dependency_links == []
    assert (lane_root / "frontend" / "node_modules").is_symlink()


def test_prepare_node_workspace_marks_missing_package_node_modules_for_install(tmp_path: Path) -> None:
    from app.worktree_node_workspace import prepare_node_workspace

    main_root = tmp_path / "projects" / "agent-hub"
    lane_root = tmp_path / "projects" / "agent-hub-lane"
    _write_workspace(main_root)
    _write_workspace(lane_root)

    _write_package_json(main_root / "frontend" / "package.json", {"name": "frontend"})
    _write_package_json(main_root / "packages" / "chat-ui" / "package.json", {"name": "chat-ui"})
    _write_package_json(lane_root / "frontend" / "package.json", {"name": "frontend"})
    _write_package_json(lane_root / "packages" / "chat-ui" / "package.json", {"name": "chat-ui"})

    (lane_root / "node_modules").mkdir(parents=True)

    result = prepare_node_workspace(lane_root, main_root, cwd="frontend")

    assert result.needs_install is True
    assert result.removed_node_modules_symlinks == []
    assert result.materialized_file_dependency_links == []
