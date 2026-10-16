"""Report-only /srv/scratch age review: protection rules and no deletion."""

from __future__ import annotations

import errno
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.tasks import _retention_scratch as scratch


@pytest.fixture
def layout(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "scratch"
    home = tmp_path / "home"
    proc = tmp_path / "proc"
    for path in (root, home, proc):
        path.mkdir()
    return {"root": root, "home": home, "proc": proc}


def review(layout: dict[str, Path], *, days: float = 10, **kwargs: object) -> scratch.ScratchReview:
    # ctime cannot be backdated; review from the future instead.
    now = datetime.now(UTC) + timedelta(days=days)
    return scratch.collect_scratch_review(
        max_age_hours=7 * 24, now=now, scratch_root=layout["root"],
        symlink_roots=[layout["home"]], proc_root=layout["proc"], **kwargs,  # type: ignore[arg-type]
    )


def paths(items: list) -> set[str]:
    return {Path(item["path"]).name for item in items}


def test_old_entries_are_reported_and_never_deleted(layout):
    old = layout["root"] / "old-download"
    (old / "nested").mkdir(parents=True)
    (old / "nested" / "blob.bin").write_bytes(b"x" * 10)
    result = review(layout)
    assert result["status"] == "report_only"
    assert paths(result["candidates"]) == {"old-download"}
    candidate = result["candidates"][0]
    assert candidate["action"] == "review_only" and candidate["entries"] == 3
    assert old.exists() and (old / "nested" / "blob.bin").exists()


def test_recent_activity_anywhere_in_entry_keeps_it(layout):
    entry = layout["root"] / "active"
    entry.mkdir()
    (entry / "fresh.txt").write_text("new")
    result = review(layout, days=1)
    assert result["candidates"] == [] and result["recent"] == 1


def test_protected_roots_are_never_candidates(layout):
    for name in ("cache", "models", ".dev-tools", "st-cleanrooms-1000"):
        (layout["root"] / name).mkdir()
    result = review(layout)
    assert result["candidates"] == []
    assert paths(result["protected"]) == {"cache", "models", ".dev-tools", "st-cleanrooms-1000"}


@pytest.mark.parametrize("relative", [False, True])
def test_symlink_targets_from_home_are_protected(layout, relative):
    target = layout["root"] / "linked-cache" / "pip"
    target.mkdir(parents=True)
    (layout["home"] / ".cache").mkdir()
    link = layout["home"] / ".cache" / "pip"
    link.symlink_to(os.path.relpath(target, link.parent) if relative else target)
    result = review(layout)
    assert result["candidates"] == []
    assert result["protected"][0]["reason"] == f"symlink target of {link}"


def test_symlink_chain_resolving_into_scratch_protects_final_target(layout):
    target = layout["root"] / "final"
    target.mkdir()
    hop = layout["home"] / "hop"
    hop.symlink_to(target)
    (layout["home"] / "entry").symlink_to(hop)
    assert review(layout)["candidates"] == []


def test_link_inside_the_entry_itself_does_not_protect_it(layout):
    entry = layout["root"] / "source-tree"
    entry.mkdir()
    (entry / "README.md").write_text("x")
    (entry / "AGENTS.md").symlink_to("README.md")
    assert paths(review(layout)["candidates"]) == {"source-tree"}


def test_top_level_scratch_pointer_protects_its_target(layout):
    (layout["root"] / "debug.log").write_text("log")
    (layout["root"] / "latest").symlink_to(layout["root"] / "debug.log")
    result = review(layout)
    assert result["candidates"] == [] and paths(result["protected"]) == {"debug.log"}


def test_symlink_scan_is_depth_bounded_and_skips_snapshots(layout):
    target = layout["root"] / "deep-target"
    target.mkdir()
    deep = layout["home"] / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "link").symlink_to(target)  # depth 5: beyond the find -maxdepth 4 bound
    snapshots = layout["home"] / ".snapshots"
    snapshots.mkdir()
    (snapshots / "link").symlink_to(target)
    assert scratch.symlink_references([layout["home"]], scratch_root=layout["root"]) == []
    shallow = layout["home"] / "a" / "b" / "c" / "link"
    shallow.symlink_to(target)
    assert scratch.symlink_references([layout["home"]], scratch_root=layout["root"]) == [(shallow, target)]


@pytest.mark.parametrize("kind", ["cwd", "fd", "maps"])
def test_paths_open_by_a_process_are_protected(layout, kind):
    entry = layout["root"] / "in-use"
    entry.mkdir()
    held = entry / "db.sqlite"
    held.write_text("x")
    process = layout["proc"] / "4242"
    (process / "fd").mkdir(parents=True)
    if kind == "cwd":
        (process / "cwd").symlink_to(entry)
    elif kind == "fd":
        (process / "fd" / "3").symlink_to(held)
    else:
        (process / "maps").write_text(f"7f00-7f01 r--p 00000000 00:2a 123   {held} (deleted)\n")
    result = review(layout)
    assert result["candidates"] == []
    assert result["protected"][0]["reason"] == "in use by pid 4242"


def test_unverifiable_large_trees_are_kept(layout):
    entry = layout["root"] / "huge"
    entry.mkdir()
    for index in range(5):
        (entry / f"f{index}").write_text("x")
    result = review(layout, max_entries=3)
    assert result["candidates"] == []
    assert "not verified" in result["protected"][0]["reason"]


def test_missing_root_is_skipped(tmp_path):
    result = scratch.collect_scratch_review(max_age_hours=1, scratch_root=tmp_path / "absent", symlink_roots=[])
    assert result["status"] == "skipped" and result["candidates"] == []


def apply(layout: dict[str, Path], *, days: float = 10, **kwargs: object) -> scratch.ScratchApply:
    now = datetime.now(UTC) + timedelta(days=days)
    return scratch.apply_scratch_retention(
        max_age_hours=7 * 24, now=now, scratch_root=layout["root"],
        symlink_roots=[layout["home"]], proc_root=layout["proc"], **kwargs,  # type: ignore[arg-type]
    )


def test_apply_deletes_only_old_unprotected_entries(layout):
    old = layout["root"] / "old-download"
    (old / "nested").mkdir(parents=True)
    (old / "nested" / "blob.bin").write_bytes(b"x" * 10)
    (layout["root"] / "old.log").write_text("log")
    (layout["root"] / "cache").mkdir()
    linked = layout["root"] / "linked"
    linked.mkdir()
    (layout["home"] / "link").symlink_to(linked)
    result = apply(layout)
    assert result["status"] == "success"
    assert {Path(path).name for path in result["deleted_paths"]} == {"old-download", "old.log"}
    assert not old.exists() and (layout["root"] / "cache").exists() and linked.exists()


def test_apply_keeps_recent_entries(layout):
    (layout["root"] / "fresh").mkdir()
    assert apply(layout, days=1)["deleted_paths"] == []
    assert (layout["root"] / "fresh").exists()


def test_weekly_runner_respects_cadence_stamp(layout, tmp_path):
    stamp = tmp_path / "state" / "scratch.json"
    (layout["root"] / "old").mkdir()
    now = datetime.now(UTC) + timedelta(days=10)
    kwargs = {"scratch_root": layout["root"], "symlink_roots": [layout["home"]], "proc_root": layout["proc"]}
    first = scratch.weekly_scratch_retention(max_age_hours=7 * 24, now=now, stamp=stamp, **kwargs)
    assert first["status"] == "success" and stamp.is_file()
    (layout["root"] / "old2").mkdir()
    again = scratch.weekly_scratch_retention(max_age_hours=7 * 24, now=now + timedelta(days=1), stamp=stamp, **kwargs)
    assert again == {"status": "skipped", "reason": "weekly-cadence", "last_applied_at": now.isoformat()}
    later = scratch.weekly_scratch_retention(max_age_hours=7 * 24, now=now + timedelta(days=7), stamp=stamp, **kwargs)
    assert [Path(path).name for path in later["deleted_paths"]] == ["old2"]


def fake_mountinfo(tmp_path: Path, *mount_points: Path) -> Path:
    """A mountinfo with '/' plus the given mount points (spaces escaped as the kernel does)."""
    lines = ["22 1 0:21 / / rw,relatime shared:1 - btrfs /dev/nvme0n1p7 rw"]
    for index, point in enumerate(mount_points, start=100):
        escaped = os.path.realpath(point).replace(" ", "\\040")
        lines.append(f"{index} 22 0:21 /@workspaces/projects {escaped} rw,relatime shared:2 - btrfs /dev/nvme0n1p8 rw")
    table = tmp_path / "mountinfo"
    table.write_text("\n".join(lines) + "\n")
    return table


@pytest.mark.parametrize("where", ["nested", "entry"])
def test_entry_holding_a_bind_mount_is_never_deleted(layout, tmp_path, where):
    """Regression: only the entry's own device was checked, so rmtree emptied a bind mount inside it."""
    entry = layout["root"] / "old work"
    mounted = entry / "data dir" if where == "nested" else entry
    mounted.mkdir(parents=True)
    (mounted / "precious.db").write_text("owner data")
    table = fake_mountinfo(tmp_path, mounted)
    reviewed = review(layout, mountinfo=table)
    assert reviewed["candidates"] == []
    assert reviewed["protected"][0]["reason"] == f"mount point {os.path.realpath(mounted)} inside"
    result = apply(layout, mountinfo=table)
    assert result["deleted_paths"] == [] and (mounted / "precious.db").exists()


def test_unreadable_mount_table_keeps_everything(layout, tmp_path):
    (layout["root"] / "old").mkdir()
    result = apply(layout, mountinfo=tmp_path / "missing-mountinfo")
    assert result["deleted_paths"] == [] and (layout["root"] / "old").exists()


def test_unrelated_mounts_do_not_protect(layout, tmp_path):
    (layout["root"] / "old").mkdir()
    sibling = tmp_path / "elsewhere"
    sibling.mkdir()
    table = fake_mountinfo(tmp_path, layout["root"], sibling)
    assert [Path(path).name for path in apply(layout, mountinfo=table)["deleted_paths"]] == ["old"]


def _fake_device(monkeypatch, name: str) -> None:
    """Report entries called ``name`` as living on another device."""
    real_stat, real_lstat = os.stat, os.lstat

    class Shifted:
        def __init__(self, result: os.stat_result) -> None:
            self._result = result
            self.st_dev = result.st_dev + 1

        def __getattr__(self, attribute: str) -> object:
            return getattr(self._result, attribute)

    def shifted(result: os.stat_result) -> Any:
        return Shifted(result)

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        return shifted(result) if os.path.basename(os.fsdecode(path)) == name else result

    def fake_lstat(path, *args, **kwargs):
        result = real_lstat(path, *args, **kwargs)
        return shifted(result) if os.path.basename(os.fsdecode(path)) == name else result

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(os, "lstat", fake_lstat)


def test_entry_with_another_filesystem_inside_is_protected(layout, monkeypatch):
    entry = layout["root"] / "old"
    (entry / "othermount").mkdir(parents=True)
    (entry / "othermount" / "keep.bin").write_text("x")
    _fake_device(monkeypatch, "othermount")
    result = apply(layout)
    assert result["deleted_paths"] == [] and (entry / "othermount" / "keep.bin").exists()
    assert review(layout)["protected"][0]["reason"] == "another filesystem inside"


def test_removal_stops_at_another_device(tmp_path, monkeypatch):
    entry = tmp_path / "old"
    (entry / "a").mkdir(parents=True)
    (entry / "a" / "gone.txt").write_text("x")
    (entry / "othermount").mkdir()
    (entry / "othermount" / "keep.bin").write_text("x")
    info = entry.lstat()
    _fake_device(monkeypatch, "othermount")
    with pytest.raises(OSError) as raised:
        scratch.remove_entry(entry, (info.st_dev, info.st_ino))
    assert raised.value.errno == errno.EXDEV
    assert (entry / "othermount" / "keep.bin").exists()


def test_removal_refuses_an_entry_swapped_since_the_check(tmp_path):
    entry = tmp_path / "old"
    entry.mkdir()
    info = entry.lstat()
    entry.rmdir()
    entry.mkdir()
    (entry / "new.txt").write_text("x")
    if entry.lstat().st_ino == info.st_ino:
        pytest.skip("filesystem reused the inode")
    with pytest.raises(OSError):
        scratch.remove_entry(entry, (info.st_dev, info.st_ino))
    assert (entry / "new.txt").exists()


def test_entry_bind_mounted_elsewhere_is_never_deleted(layout, tmp_path):
    """Regression: only mounts inside an entry were checked, so a bind mount sourced from it lost its data."""
    entry = layout["root"] / "old"
    (entry / "exported").mkdir(parents=True)
    (entry / "exported" / "precious.db").write_text("owner data")
    (layout["root"] / "plain").mkdir()
    scratch_point = os.path.realpath(layout["root"])
    table = tmp_path / "mountinfo"
    table.write_text("22 1 0:21 / / rw - btrfs /dev/p7 rw\n"
                     f"120 22 0:43 /@disposable {scratch_point} rw - btrfs /dev/p8 rw\n"
                     "130 22 0:43 /@disposable/old/exported /mnt/live rw - btrfs /dev/p8 rw\n"
                     "140 22 0:43 /@disposable/plain-other /mnt/other rw - btrfs /dev/p8 rw\n")
    assert scratch.mount_skip_reason(entry, table) == "bind-mounted at /mnt/live"
    result = apply(layout, mountinfo=table)
    assert [Path(path).name for path in result["deleted_paths"]] == ["plain"]
    assert (entry / "exported" / "precious.db").exists()


def test_removal_stops_at_a_same_filesystem_bind_mount(tmp_path, monkeypatch):
    """A bind mount made after the check shares st_dev; the mount id still stops removal before emptying it."""
    entry = tmp_path / "old"
    (entry / "bound").mkdir(parents=True)
    (entry / "bound" / "keep.bin").write_text("x")
    info = entry.lstat()
    real_mount_id = scratch._mount_id

    def fake_mount_id(fd: int) -> int:
        bound = os.path.basename(os.readlink(f"/proc/self/fd/{fd}")) == "bound"
        return real_mount_id(fd) + 1000 if bound else real_mount_id(fd)

    monkeypatch.setattr(scratch, "_mount_id", fake_mount_id)
    with pytest.raises(OSError) as raised:
        scratch.remove_entry(entry, (info.st_dev, info.st_ino))
    assert raised.value.errno == errno.EXDEV
    assert (entry / "bound" / "keep.bin").exists()
