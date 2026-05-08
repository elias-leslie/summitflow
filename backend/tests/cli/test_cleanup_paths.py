from __future__ import annotations

from pathlib import Path

import pytest
import typer

from cli.commands.cleanup_paths import validate_cleanup_target


def test_cleanup_path_allows_configured_non_repo_root_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    target = allowed_root / "stale-mirror"
    target.mkdir(parents=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setenv("SUMMITFLOW_CLEANUP_ALLOWED_ROOTS", str(allowed_root))

    result = validate_cleanup_target(str(target), repo_root, recursive=True)

    assert result.absolute_path == target
    assert result.relative_path == "stale-mirror"
    assert result.path_type == "directory"


def test_cleanup_path_rejects_allowed_non_repo_root_itself(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setenv("SUMMITFLOW_CLEANUP_ALLOWED_ROOTS", str(allowed_root))

    with pytest.raises(typer.Exit):
        validate_cleanup_target(str(allowed_root), repo_root, recursive=True)
