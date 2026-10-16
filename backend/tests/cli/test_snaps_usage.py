"""st snaps lists from the manifest and measures disk usage only on request."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from cli.commands import snapshots
from cli.lib.snapshots._models import QuickSnapshot, SnapshotUsage


def _snapshot(snapshot_id: str) -> QuickSnapshot:
    return QuickSnapshot(
        id=snapshot_id, name=None, project_id="demo", repo_root="/r", scope_path="/r",
        scope_type="project", scope_name="demo", snapshot_path=f"/s/{snapshot_id}", branch=None,
        head_oid=None, head_ref=None, git_dir="/r/.git", index_artifact_path=None,
        created_at="2026-10-16T00:00:00+00:00",
    )


def _run(monkeypatch, *args: str):
    measured: list[str] = []

    def usage(snapshot):
        measured.append(snapshot.id)
        return SnapshotUsage(total_bytes=2048, exclusive_bytes=1024, shared_bytes=1024)

    monkeypatch.setattr(snapshots, "get_config", lambda: SimpleNamespace(project_id="demo"))
    monkeypatch.setattr(snapshots, "list_snapshots", lambda *, project_id: [_snapshot("a"), _snapshot("b")])
    monkeypatch.setattr(snapshots, "get_snapshot_usage", usage)
    result = CliRunner().invoke(snapshots.app, ["snaps", *args])
    assert result.exit_code == 0, result.output
    return result.output, measured


def test_snaps_skips_btrfs_du_by_default(monkeypatch) -> None:
    output, measured = _run(monkeypatch)
    assert measured == []
    assert output.splitlines()[0] == "SNAPS[2]"
    assert "total:" not in output


def test_snaps_usage_flag_measures_each_snapshot(monkeypatch) -> None:
    output, measured = _run(monkeypatch, "--usage")
    assert measured == ["a", "b"]
    assert output.splitlines()[0] == "SNAPS[2]|total:4.0KiB|exclusive:2.0KiB|shared:2.0KiB"
    assert output.splitlines()[1].endswith("|total:2.0KiB|exclusive:1.0KiB|shared:1.0KiB")
