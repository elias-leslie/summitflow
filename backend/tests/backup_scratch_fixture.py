"""Opt-in scratch evidence shared by bounded backup task and CLI fixtures."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def backup_job_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.utils import transient_scratch as scratch

    root = tmp_path / "mounted-scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(scratch, "SCRATCH_ROOT", root)
    original_is_mount = Path.is_mount
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root or original_is_mount(path))
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))
    return root
