"""Report-only /srv/scratch age review: protection rules and no deletion."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
