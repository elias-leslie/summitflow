from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import typer

from cli.commands import cleanup
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
    monkeypatch.setattr(cleanup, "_execute_snapshot_deletions", lambda residues: (0, ["agent-hub/bad: boom"]))

    with pytest.raises(typer.Exit) as exc_info:
        cleanup.run_snapshot_deletions([residue], dry_run=False)

    assert exc_info.value.exit_code == 1
