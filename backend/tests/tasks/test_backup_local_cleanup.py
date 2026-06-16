"""Tests for local backup archive filesystem cleanup."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.tasks.backup_local_cleanup import cleanup_local_backup_archives


def _touch(path: Path, *, now: datetime, age_days: int, size: int = 7) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    timestamp = (now - timedelta(days=age_days)).timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def test_cleanup_local_backup_archives_preserves_current_db_locations(tmp_path: Path) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    root = tmp_path / "Backups" / "project-backups"
    current = _touch(root / "summitflow" / "summitflow-20260501-120000.tar.gz", now=now, age_days=46)
    orphan = _touch(root / "summitflow" / "summitflow-20260502-120000.tar.gz", now=now, age_days=45)

    result = cleanup_local_backup_archives(
        dry_run=False,
        now=now,
        roots=[root],
        current_locations=[current],
        sources=[{"id": "summitflow", "retention_days": 30}],
    )

    assert current.exists()
    assert not orphan.exists()
    assert result["scanned"] == 2
    assert result["kept_current"] == 1
    assert result["deleted"] == 1
    assert result["bytes_deleted"] == 7


def test_cleanup_local_backup_archives_dry_run_does_not_delete(tmp_path: Path) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    root = tmp_path / "Backups" / "project-backups"
    orphan = _touch(root / "agent-hub" / "agent-hub-20260501-120000.tar.gz", now=now, age_days=46)

    result = cleanup_local_backup_archives(
        dry_run=True,
        now=now,
        roots=[root],
        current_locations=[],
        sources=[{"id": "agent-hub", "retention_days": 30}],
    )

    assert orphan.exists()
    assert result["status"] == "dry_run"
    assert result["candidate_count"] == 1
    assert result["deleted"] == 0


def test_cleanup_local_backup_archives_skips_recent_orphans(tmp_path: Path) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    root = tmp_path / "Backups" / "project-backups"
    orphan = _touch(root / "portfolio-ai" / "portfolio-ai-20260610-120000.tar.gz", now=now, age_days=6)

    result = cleanup_local_backup_archives(
        dry_run=False,
        now=now,
        roots=[root],
        current_locations=[],
        sources=[{"id": "portfolio-ai", "retention_days": 30}],
    )

    assert orphan.exists()
    assert result["skipped_recent"] == 1
    assert result["deleted"] == 0
