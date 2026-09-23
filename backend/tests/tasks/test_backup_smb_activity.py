"""SMB archive transfer shares bulk lifecycle; metadata keeps its bound."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.tasks import backup_native_smb as smb


@pytest.mark.parametrize("returncode", [0, 7])
def test_smb_upload_uses_bulk_lifecycle_and_preserves_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.touch()
    storage = smb.StorageConfig("host", "share", "backups", "user", credentials)
    archive = tmp_path / "archive.age"
    archive.write_bytes(b"ciphertext")
    runner = Mock(return_value=subprocess.CompletedProcess([], returncode, archive.name, "provider error"))
    metadata = Mock(side_effect=AssertionError("bulk upload must not use metadata timeout"))
    monkeypatch.setattr(smb, "run_bulk_process", runner, raising=False)
    monkeypatch.setattr(smb.subprocess, "run", metadata)
    monkeypatch.setattr(smb.shutil, "which", lambda _: "smbclient")
    monkeypatch.setattr(smb, "_ensure_smb_dir", lambda _: smb.SmbUploadResult(True, "", "backups", "location"))

    result = smb._smb_upload(archive, archive.name, storage)

    assert result.ok is (returncode == 0)
    assert result.returncode == returncode
    assert runner.call_args.kwargs == {"phase": "local-storage", "attention_after": 300}
    assert "put" in runner.call_args.args[0][-1]
    assert archive.read_bytes() == b"ciphertext"
    if returncode:
        assert result.error and "provider error" in result.error


def test_smb_metadata_keeps_existing_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = smb.StorageConfig("host", "share", "backups", "user", tmp_path / "credentials")
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(smb.subprocess, "run", runner)
    monkeypatch.setattr(smb, "run_bulk_process", Mock(side_effect=AssertionError("metadata is bounded")), raising=False)

    assert smb._smb_cd_ok(storage, "backups") is True
    assert runner.call_args.kwargs["timeout"] == 30
