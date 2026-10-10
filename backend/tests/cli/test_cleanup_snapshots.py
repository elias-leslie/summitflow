from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import typer

from cli.commands import cleanup, cleanup_snapshots_cmd
from cli.lib import quick_snapshots
from cli.lib.quick_snapshots import SnapshotError
from cli.lib.snapshots._cleanup import SnapshotResidue


def test_delete_snapshot_residue_removes_nested_btrfs_subvolumes_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "legacy-root"
    nested = root / "projects" / "old-project" / "snapshot-1"
    sibling = root / "projects" / "old-project" / "snapshot-2"
    nested.mkdir(parents=True)
    sibling.mkdir()
    calls: list[Path] = []

    def fake_delete_subvolume(path: Path) -> None:
        calls.append(path)
        if path in {nested, sibling}:
            shutil.rmtree(path)
            return
        raise SnapshotError("Btrfs command failed: Invalid argument")

    monkeypatch.setattr(quick_snapshots, "_delete_subvolume", fake_delete_subvolume)

    quick_snapshots.delete_snapshot_residue(
        SnapshotResidue(
            project_id=None,
            residue_name="legacy-root",
            path=root,
            residue_type="legacy-snapshot-root",
        )
    )

    assert not root.exists()
    assert calls.index(nested) < calls.index(root)
    assert calls.index(sibling) < calls.index(root)


def test_delete_snapshot_residue_uses_privileged_helper_for_readonly_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: unprivileged deletion of read-only residue failed with EROFS."""
    from cli.lib.snapshots import _pruning

    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    root = tmp_path / ".snapshots" / "legacy-root"
    point = root / "projects" / "old" / "point"
    point.mkdir(parents=True)

    def fake_delete_subvolume(path: Path) -> None:
        if path == point:
            raise SnapshotError("Btrfs command failed\nERROR: Could not destroy subvolume/snapshot: Read-only file system")
        raise SnapshotError("Btrfs command failed: Not a Btrfs subvolume")

    privileged: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        privileged.append(command)
        shutil.rmtree(Path(command[6]))

    monkeypatch.setattr(quick_snapshots, "_delete_subvolume", fake_delete_subvolume)
    monkeypatch.setattr(_pruning.subprocess, "run", fake_run)

    quick_snapshots.delete_snapshot_residue(
        SnapshotResidue(project_id=None, residue_name="legacy-root", path=root, residue_type="legacy-snapshot-root")
    )

    assert not root.exists()
    assert len(privileged) == 1
    assert privileged[0][:5] == ["sudo", "-n", "/usr/bin/python3", "-I", "-c"]
    assert privileged[0][6:8] == [str(point), str(point.parent)]


def test_readonly_residue_helper_refuses_paths_outside_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.lib.snapshots import _pruning

    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    outside = tmp_path / "projects" / "live"
    outside.mkdir(parents=True)
    monkeypatch.setattr(_pruning.subprocess, "run", lambda *a, **k: pytest.fail("must not escalate"))
    for target in (outside, tmp_path / ".snapshots"):
        with pytest.raises(SnapshotError, match="outside the managed snapshot store"):
            _pruning.delete_readonly_residue(target)
    assert outside.exists()


def test_snapshot_deletions_exit_nonzero_on_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    residue = SnapshotResidue(
        project_id="agent-hub",
        residue_name="bad-snapshot-root",
        path=tmp_path / "bad-snapshot-root",
        residue_type="legacy-snapshot-root",
    )
    monkeypatch.setattr(
        cleanup_snapshots_cmd,
        "execute_snapshot_deletions",
        lambda residues: (0, ["agent-hub/bad: boom"]),
    )

    with pytest.raises(typer.Exit) as exc_info:
        cleanup.run_snapshot_deletions([residue], dry_run=False)

    assert exc_info.value.exit_code == 1
