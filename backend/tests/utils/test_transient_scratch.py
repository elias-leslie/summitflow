"""Scratch policy uses only synthetic mounts, files, and capacity evidence."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
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


def test_configured_missing_mount_never_uses_portable_root_fallback(tmp_path, monkeypatch):
    root = tmp_path / "missing-scratch"
    fstab = tmp_path / "fstab"
    fstab.write_text(f"UUID=fixture {root} btrfs defaults 0 0\n")
    monkeypatch.setattr(scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(scratch, "_FSTAB", fstab, raising=False)
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    with pytest.raises(scratch.ScratchError, match=r"configured.*mount"):
        scratch.managed_temp_parent("st-test", label="Validation")


def test_unconfigured_absent_mount_keeps_portable_fallback(tmp_path, monkeypatch):
    fstab = tmp_path / "fstab"
    fstab.write_text("# portable machine without a scratch mount\n")
    monkeypatch.setattr(scratch, "SCRATCH_ROOT", tmp_path / "missing")
    monkeypatch.setattr(scratch, "_FSTAB", fstab, raising=False)
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))
    assert scratch.managed_temp_parent("st-test", label="Validation") == Path("/var/tmp")


@pytest.mark.parametrize("unsafe", ["unmounted", "symlink", "shared", "private-mode", "private-link"])
def test_managed_validation_never_falls_back_from_present_unsafe_mount(mounted, monkeypatch, tmp_path, unsafe):
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    if unsafe == "unmounted":
        monkeypatch.setattr(Path, "is_mount", lambda _path: False)
    elif unsafe == "symlink":
        link = tmp_path / "link"
        link.symlink_to(mounted)
        monkeypatch.setattr(scratch, "SCRATCH_ROOT", link)
    elif unsafe == "shared":
        mounted.chmod(0o777)
    elif unsafe == "private-mode":
        (mounted / f"st-test-{os.getuid()}").mkdir(mode=0o755)
    else:
        (mounted / f"st-test-{os.getuid()}").symlink_to(tmp_path)
    with pytest.raises(scratch.ScratchError, match="unavailable or unsafe"):
        scratch.managed_temp_parent("st-test", label="Validation")


def test_managed_validation_preserves_private_inherited_mapping_before_host_lookup(mounted, tmp_path, monkeypatch):
    inherited = tmp_path / "inherited"
    inherited.mkdir(mode=0o700)
    monkeypatch.setenv("ST_NATIVE_TMP_HOST_ROOT", str(inherited))
    monkeypatch.setattr(Path, "is_mount", lambda _path: False)
    assert scratch.managed_temp_parent("st-test", label="Validation") == inherited
    assert not list(mounted.iterdir())


@pytest.mark.parametrize("unsafe", ["shared", "symlink", "relative"])
def test_managed_validation_rejects_unsafe_inherited_mapping(mounted, tmp_path, monkeypatch, unsafe):
    inherited = tmp_path / "inherited"
    inherited.mkdir(mode=0o755 if unsafe == "shared" else 0o700)
    if unsafe == "symlink":
        link = tmp_path / "alias"
        link.symlink_to(inherited)
        inherited = link
    monkeypatch.setenv("ST_NATIVE_TMP_HOST_ROOT", "relative" if unsafe == "relative" else str(inherited))
    with pytest.raises(scratch.ScratchError, match="unavailable or unsafe"):
        scratch.managed_temp_parent("st-test", label="Validation")
    assert not list(mounted.iterdir())


def test_managed_validation_budgets_materialization_before_reserve(mounted, monkeypatch):
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    usage = shutil.disk_usage(mounted)
    observed = []

    def disk_usage(path):
        observed.append(path)
        return usage._replace(free=25 * 1024**3 + 100)

    monkeypatch.setattr(scratch.shutil, "disk_usage", disk_usage)
    parent = scratch.managed_temp_parent("st-test", label="Validation", required_bytes=100)
    with pytest.raises(scratch.ScratchError, match="101 additional known bytes"):
        scratch.managed_temp_parent("st-test", label="Validation", required_bytes=101)
    assert observed == [parent, parent]
    assert not list(parent.iterdir())


def test_capacity_admission_needs_no_database_configuration(tmp_path):
    backend = Path(__file__).resolve().parents[2]
    script = (
        f"import sys; sys.path.insert(0, {str(backend)!r})\n"
        "from pathlib import Path\n"
        "from app.utils.transient_scratch import ensure_scratch_capacity\n"
        "ensure_scratch_capacity(Path.cwd(), 0)\n"
        "assert 'app.config' not in sys.modules\n"
    )
    result = subprocess.run([sys.executable, "-P", "-c", script], cwd=tmp_path,
                            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
                                 "SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB": "0"},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scratch_backed", [True, False])
def test_private_overlay_admission_does_not_allocate_on_read_only_host_mount(mounted, tmp_path, monkeypatch, scratch_backed):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("1 0 0:1 /private /var/tmp rw - btrfs fixture rw\n")
    monkeypatch.setattr(scratch, "_MOUNTINFO", mountinfo)
    monkeypatch.delenv("ST_NATIVE_TMP_HOST_ROOT", raising=False)
    private_info = mounted.stat()
    if not scratch_backed:
        values = list(private_info)
        values[2] += 1  # stat.st_dev: a private overlay on another filesystem.
        private_info = os.stat_result(values)
    original_stat, original_lstat, original_mkdir = Path.stat, Path.lstat, Path.mkdir
    monkeypatch.setattr(Path, "stat", lambda path, *args, **kwargs: private_info if path == Path("/var/tmp") else original_stat(path, *args, **kwargs))
    monkeypatch.setattr(Path, "lstat", lambda path: private_info if path == Path("/var/tmp") else original_lstat(path))

    def read_only_host(path, *args, **kwargs):
        if path.parent == mounted:
            raise OSError("fixture read-only host scratch")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", read_only_host)
    if scratch_backed:
        assert scratch.managed_temp_parent("st-first-use", label="Validation") == Path("/var/tmp")
    else:
        with pytest.raises(scratch.ScratchError, match="read-only host scratch"):
            scratch.managed_temp_parent("st-first-use", label="Validation")
    assert not list(mounted.iterdir())
