"""Scratch policy uses only synthetic mounts, files, and capacity evidence."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from app.utils import transient_scratch as scratch


@pytest.fixture
def mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    return root


@pytest.mark.parametrize("raises", [False, True])
def test_restore_scratch_is_private_ignores_tmpdir_and_cleans_up(mounted, monkeypatch, raises):
    monkeypatch.setenv("TMPDIR", "/caller/namespace")
    job = None
    try:
        with scratch.restore_scratch("fixture-", required_bytes=1024) as job:
            assert job.parent == mounted / f"st-restores-{os.getuid()}"
            assert stat.S_IMODE(job.stat().st_mode) == 0o700
            assert stat.S_IMODE(job.parent.stat().st_mode) == 0o700
            (job / "plaintext").write_bytes(b"fixture")
            if raises:
                raise InterruptedError("fixture cancellation")
    except InterruptedError:
        assert raises
    assert job is not None and not job.exists()
    assert os.environ["TMPDIR"] == "/caller/namespace"


@pytest.mark.parametrize("unsafe", ["missing", "unmounted", "symlink", "shared", "private-mode", "private-link"])
def test_required_restore_mount_never_falls_back(mounted, monkeypatch, tmp_path, unsafe):
    if unsafe == "missing":
        monkeypatch.setattr(scratch, "SCRATCH_ROOT", tmp_path / "missing")
    elif unsafe == "unmounted":
        monkeypatch.setattr(Path, "is_mount", lambda _path: False)
    elif unsafe == "symlink":
        link = tmp_path / "link"
        link.symlink_to(mounted)
        monkeypatch.setattr(scratch, "SCRATCH_ROOT", link)
    elif unsafe == "shared":
        mounted.chmod(0o777)
    elif unsafe == "private-mode":
        (mounted / f"st-restores-{os.getuid()}").mkdir(mode=0o755)
    else:
        (mounted / f"st-restores-{os.getuid()}").symlink_to(tmp_path)
    with pytest.raises(scratch.ScratchError, match="unavailable or unsafe"), scratch.restore_scratch("fixture-"):
        pytest.fail("unsafe scratch must not admit a restore")


def test_capacity_uses_actual_destination_and_existing_reserve(mounted, monkeypatch):
    observed = []
    usage = shutil.disk_usage(mounted)
    reserve = 25 * 1024**3

    def disk_usage(path):
        observed.append(path)
        return usage._replace(free=reserve + 100)

    monkeypatch.setattr(scratch.shutil, "disk_usage", disk_usage)
    scratch.ensure_scratch_capacity(mounted, 100)
    with pytest.raises(scratch.ScratchError, match="101 additional known bytes"):
        scratch.ensure_scratch_capacity(mounted, 101)
    assert observed == [mounted, mounted]
    with pytest.raises(scratch.ScratchError), scratch.restore_scratch("refused-", required_bytes=101):
        pytest.fail("insufficient reserve must precede creation")
    assert not list(mounted.glob("st-restores-*/*"))


def test_tree_measurement_does_not_follow_saved_links(mounted, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    (mounted / "inside").write_bytes(b"inside")
    (mounted / "link").symlink_to(outside)
    assert scratch.tree_bytes(mounted) == len(b"inside")
