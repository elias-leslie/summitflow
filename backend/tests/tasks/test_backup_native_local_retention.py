"""Offline copies survive local rotation until their replica is verified."""
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.tasks.backup_native_storage import apply_local_retention


@pytest.mark.parametrize("state", ["pending", "failed"])
def test_local_retention_preserves_offsite_backlog_and_three_completed_points(tmp_path: Path, state: str) -> None:
    for number in range(5):
        archive = tmp_path / f"source-{number}.tar.gz.age"
        archive.write_bytes(b"fixture")
        timestamp = (datetime.now(UTC) - timedelta(days=40 + number)).timestamp()
        os.utime(archive, (timestamp, timestamp))
    (tmp_path / "offsite-manifest.json").write_text(json.dumps({"archives": [{"archive_name": "source-4.tar.gz.age", "status": state}]}))
    apply_local_retention(tmp_path, retention_days=7)
    assert sorted(path.name for path in tmp_path.glob("*.age")) == ["source-0.tar.gz.age", "source-1.tar.gz.age", "source-2.tar.gz.age", "source-4.tar.gz.age"]


def test_unknown_offsite_manifest_does_not_authorize_deletion(tmp_path: Path) -> None:
    archives = [tmp_path / f"old-{n}.tar.gz.age" for n in range(4)]
    for archive in archives:
        archive.write_bytes(b"fixture")
        os.utime(archive, (0, 0))
    (tmp_path / "offsite-manifest.json").write_text("damaged")
    apply_local_retention(tmp_path, retention_days=7)
    assert all(archive.exists() for archive in archives)
