"""Independent acceptance checks for backup recovery guarantees."""

from __future__ import annotations

import gzip
import io
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

from app.services import backup_keys
from app.tasks.backup_native_archive import DEFAULT_EXCLUDES, _should_exclude
from app.tasks.backup_native_offsite import encrypt_completed_archive
from app.tasks.backup_native_recovery import (
    build_consistent_snapshot,
    restore_git_recovery,
)


def _git(project: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def test_restored_index_preserves_newly_staged_blob_content(tmp_path: Path) -> None:
    """A copied index is not recoverable unless its staged objects are bundled."""
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Recovery Review")
    _git(source, "config", "user.email", "review@example.invalid")
    (source / "tracked.txt").write_text("committed\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    _git(source, "commit", "-m", "base")

    staged_content = "valuable staged-only content\n"
    (source / "staged-only.txt").write_text(staged_content, encoding="utf-8")
    _git(source, "add", "staged-only.txt")

    staging = tmp_path / "staging"
    staging.mkdir()
    snapshot, _recovery = build_consistent_snapshot(
        source,
        staging,
        DEFAULT_EXCLUDES,
        _should_exclude,
    )
    restored = tmp_path / "restored"
    restored.mkdir()
    for entry in snapshot.iterdir():
        entry.rename(restored / entry.name)

    result = restore_git_recovery(restored)
    indexed = _git(restored, "show", ":staged-only.txt", check=False)

    assert result["git_restored"] is True
    assert indexed.returncode == 0, indexed.stderr
    assert indexed.stdout == staged_content


def test_infrastructure_restore_test_accepts_new_encrypted_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The existing restore-test path must materialize `.age` ciphertext first."""
    from app.tasks import backup_restore_test

    key_dir = tmp_path / "keys"
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(key_dir))
    backup_keys.setup_backup_key()
    _key_id, recovery_key = backup_keys.export_backup_recovery_key()
    backup_keys.verify_backup_recovery_key(recovery_key)

    plaintext = tmp_path / "infrastructure-20260921-120000.tar.gz"
    dump = gzip.compress(b"-- PostgreSQL database cluster dump\n")
    with tarfile.open(plaintext, "w:gz") as archive:
        member = tarfile.TarInfo("infrastructure/pgdumpall.sql.gz")
        member.size = len(dump)
        archive.addfile(member, io.BytesIO(dump))
    ciphertext = plaintext.with_suffix(plaintext.suffix + ".age")
    encryption = encrypt_completed_archive(plaintext, ciphertext, {})
    assert isinstance(encryption["duration_ms"], int)
    assert encryption["duration_ms"] >= 0

    recorded: list[tuple[bool, str | None]] = []
    monkeypatch.setattr(
        backup_restore_test.backup_store,
        "update_source_restore_test",
        lambda _source_id, *, ok, error=None: recorded.append((ok, error)),
    )
    monkeypatch.setattr(
        backup_restore_test,
        "verify_archive_coverage",
        lambda _verification: SimpleNamespace(
            complete=True,
            required_count=1,
            present_count=1,
            missing=[],
        ),
    )
    monkeypatch.setattr(backup_restore_test, "_validate_pgdump_header", lambda _path: True)
    monkeypatch.setattr(backup_restore_test, "_validate_redis_header", lambda _path: True)

    result = backup_restore_test._validate_infra_archive(
        "infrastructure",
        {
            "id": "backup-1",
            "location": str(ciphertext),
            "name": ciphertext.name,
            "verification_json": {},
        },
    )

    assert result["ok"] is True, result
    assert recorded == [(True, None)]
