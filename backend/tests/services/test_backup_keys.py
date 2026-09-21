"""Disposable age-key tests; never use the production backup key directory."""

from __future__ import annotations

import shutil
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import backup_keys

pytestmark = pytest.mark.skipif(
    not shutil.which("age") or not shutil.which("age-keygen"),
    reason="age tooling is not installed",
)


@pytest.fixture
def key_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "private-keys"
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(target))
    return target


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_setup_is_idempotent_private_and_not_ready_before_owner_proof(key_dir: Path) -> None:
    with pytest.raises(backup_keys.BackupKeyUnavailableError, match="backup_key_not_configured"):
        backup_keys.get_backup_key_paths()

    first = backup_keys.setup_backup_key()
    second = backup_keys.setup_backup_key()
    recipient_file, identity_file = backup_keys.get_backup_key_paths(require_validated=False)

    assert first == second
    assert first["configured"] is True
    assert first["ready"] is False
    assert first["identity_exported"] is False
    assert _mode(key_dir) == 0o700
    assert _mode(recipient_file) == 0o600
    assert _mode(identity_file) == 0o600
    assert all(_mode(path) == 0o600 for path in key_dir.iterdir() if path.is_file())
    assert "AGE-SECRET-KEY" not in repr(first)
    with pytest.raises(backup_keys.BackupKeyUnavailableError, match="backup_key_not_verified"):
        backup_keys.get_backup_key_paths()


def test_export_then_verify_proves_saved_key_roundtrip(key_dir: Path) -> None:
    setup = backup_keys.setup_backup_key()
    key_id, recovery_key = backup_keys.export_backup_recovery_key()
    exported = backup_keys.get_backup_key_status()
    verified = backup_keys.verify_backup_recovery_key(recovery_key)

    assert key_id == setup["key_id"]
    assert recovery_key.startswith("AGE-SECRET-KEY-")
    assert exported["identity_exported"] is True
    assert exported["ready"] is False
    assert verified["ready"] is True
    assert verified["roundtrip_verified_at"]
    assert backup_keys.get_backup_key_paths() == backup_keys.get_backup_key_paths(
        require_validated=False
    )


def test_import_existing_key_proves_roundtrip_without_replacing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source-keys"
    imported = tmp_path / "imported-keys"
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(source))
    generated = backup_keys.setup_backup_key()
    key_id, recovery_key = backup_keys.export_backup_recovery_key()

    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(imported))
    status = backup_keys.import_backup_recovery_key(recovery_key)
    _recipient_file, identity_file = backup_keys.get_backup_key_paths()

    assert status["ready"] is True
    assert status["identity_exported"] is True
    assert status["key_id"] == key_id == generated["key_id"]
    assert identity_file.read_text(encoding="utf-8").strip() == recovery_key
    with pytest.raises(
        backup_keys.BackupKeyUnavailableError,
        match="backup_key_already_configured",
    ):
        backup_keys.import_backup_recovery_key(recovery_key)
    assert identity_file.read_text(encoding="utf-8").strip() == recovery_key


def test_wrong_recovery_key_does_not_mark_configured_key_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(first))
    backup_keys.setup_backup_key()
    expected_id = backup_keys.get_backup_key_status()["key_id"]
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(second))
    backup_keys.setup_backup_key()
    _other_id, wrong_key = backup_keys.export_backup_recovery_key()
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(first))

    with pytest.raises(
        backup_keys.BackupKeyVerificationError, match="recovery_key_does_not_match"
    ):
        backup_keys.verify_backup_recovery_key(wrong_key)

    status = backup_keys.get_backup_key_status()
    assert status["key_id"] == expected_id
    assert status["ready"] is False


def test_incomplete_key_material_is_never_silently_regenerated(key_dir: Path) -> None:
    key_dir.mkdir(mode=0o700)
    recipient = key_dir / "backup-recipient.txt"
    recipient.write_text("age1incomplete\n")
    recipient.chmod(0o600)

    with pytest.raises(backup_keys.BackupKeyUnavailableError, match="backup_key_incomplete"):
        backup_keys.setup_backup_key()

    assert not (key_dir / "backup-identity.agekey").exists()


def test_concurrent_setup_returns_one_identity(key_dir: Path) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _index: backup_keys.setup_backup_key(), range(2)))

    assert statuses[0]["key_id"] == statuses[1]["key_id"]
    assert len(list(key_dir.glob("*.agekey"))) == 1


def test_status_contains_no_private_identity(key_dir: Path) -> None:
    backup_keys.setup_backup_key()
    _key_id, recovery_key = backup_keys.export_backup_recovery_key()

    status_text = repr(backup_keys.get_backup_key_status())

    assert recovery_key not in status_text
    assert "private_identity_file" not in status_text
    assert backup_keys.backup_key_directory() == key_dir.absolute()


def test_preexisting_nonprivate_directory_is_rejected_without_chmod_or_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared_directory = tmp_path / "shared-directory"
    shared_directory.mkdir(mode=0o755)
    shared_directory.chmod(0o755)
    marker = shared_directory / "unrelated.txt"
    marker.write_text("preserve", encoding="utf-8")
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(shared_directory))

    with pytest.raises(
        backup_keys.BackupKeyUnavailableError,
        match="backup_key_directory_unsafe",
    ):
        backup_keys.setup_backup_key()

    assert _mode(shared_directory) == 0o755
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert list(shared_directory.iterdir()) == [marker]


def test_symlink_component_is_rejected_without_following_or_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    configured = linked_parent / "private-keys"
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(configured))

    assert backup_keys.backup_key_directory() == configured.absolute()
    with pytest.raises(
        backup_keys.BackupKeyUnavailableError,
        match="backup_key_directory_unsafe",
    ):
        backup_keys.setup_backup_key()
    assert not (real_parent / "private-keys").exists()


def test_age_tool_invocation_has_no_arbitrary_short_timeout(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(["age"], 0, stdout=b"ok", stderr=b"")
    mock_run = Mock(return_value=completed)
    monkeypatch.setattr(backup_keys.safe_subprocess, "run", mock_run)

    assert backup_keys._run_age(["age"], input_bytes=b"small") == b"ok"
    assert "timeout" not in mock_run.call_args.kwargs
