from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.services import backup_keys
from app.tasks.backup_native_archive import archive_sha256
from tests.backup_scratch_fixture import backup_job_scratch  # noqa: F401

pytestmark = pytest.mark.usefixtures("backup_job_scratch")

runner = CliRunner()


def _git(project: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _encrypted_project_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, str]:
    from app.tasks import backup_native_archive
    from app.tasks.backup_native_offsite import encrypt_completed_archive

    key_dir = tmp_path / "runtime-keys"
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(key_dir))
    backup_keys.setup_backup_key()
    _key_id, recovery_key = backup_keys.export_backup_recovery_key()
    backup_keys.verify_backup_recovery_key(recovery_key)
    saved_identity = tmp_path / "saved-recovery.agekey"
    saved_identity.write_text(recovery_key + "\n", encoding="utf-8")
    saved_identity.chmod(0o600)

    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Recovery Fixture")
    _git(project, "config", "user.email", "recovery@example.invalid")
    (project / "history.txt").write_text("first\n", encoding="utf-8")
    _git(project, "add", "history.txt")
    _git(project, "commit", "-m", "first")
    (project / "history.txt").write_text("second\n", encoding="utf-8")
    _git(project, "add", "history.txt")
    _git(project, "commit", "-m", "second")
    (project / "staged-only.txt").write_text("recover staged content\n", encoding="utf-8")
    _git(project, "add", "staged-only.txt")

    monkeypatch.setattr(backup_native_archive, "_dump_database", lambda *_args: (0, False))
    staging = tmp_path / "staging"
    staging.mkdir()
    result = backup_native_archive._create_project_archive(project, "project", staging, {})
    plaintext = Path(result["archive_path"])
    ciphertext = tmp_path / f"{plaintext.name}.age"
    encrypt_completed_archive(plaintext, ciphertext, {})
    return ciphertext, saved_identity, archive_sha256(ciphertext)


def test_offline_restore_avoids_db_and_recovers_git_history_and_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.storage import backups as backup_store
    from cli.commands import backup as backup_command
    from cli.commands import backup_runtime
    from cli.main import app

    ciphertext, identity, checksum = _encrypted_project_backup(tmp_path, monkeypatch)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("online project/API/backup store path used")

    monkeypatch.setattr(backup_command, "get_config", forbidden)
    monkeypatch.setattr(backup_command, "STClient", forbidden)
    monkeypatch.setattr(backup_command, "_get_project_api", forbidden)
    monkeypatch.setattr(backup_command, "_get_source_api", forbidden)
    for name, value in vars(backup_store).items():
        if callable(value) and not name.startswith("_"):
            monkeypatch.setattr(backup_store, name, forbidden)
    monkeypatch.setattr(
        backup_runtime,
        "restore_backup_isolated",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DB path used")),
    )
    destination = tmp_path / "recovered"

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "--file",
            str(ciphertext),
            "--into",
            str(destination),
            "--identity-file",
            str(identity),
            "--expected-checksum",
            checksum,
        ],
    )

    assert result.exit_code == 0, result.output
    assert _git(destination, "rev-list", "--count", "HEAD").stdout.strip() == "2"
    assert _git(destination, "show", ":staged-only.txt").stdout == "recover staged content\n"
    assert "A  staged-only.txt" in _git(destination, "status", "--short").stdout
    assert "no database was restored" in result.output
    assert "Ciphertext SHA-256 matched" in result.output


def test_offline_restore_rejects_wrong_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.main import app

    ciphertext, _identity, _checksum = _encrypted_project_backup(tmp_path, monkeypatch)
    wrong_key_dir = tmp_path / "wrong-runtime-keys"
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(wrong_key_dir))
    backup_keys.setup_backup_key()
    _key_id, wrong_key = backup_keys.export_backup_recovery_key()
    wrong_identity = tmp_path / "wrong.agekey"
    wrong_identity.write_text(wrong_key + "\n", encoding="utf-8")
    wrong_identity.chmod(0o600)

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "--file",
            str(ciphertext),
            "--into",
            str(tmp_path / "recovered"),
            "--identity-file",
            str(wrong_identity),
        ],
    )

    assert result.exit_code == 1
    assert "age decryption failed" in result.output


def test_offline_restore_rejects_nonempty_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.main import app

    ciphertext, identity, _checksum = _encrypted_project_backup(tmp_path, monkeypatch)
    destination = tmp_path / "recovered"
    destination.mkdir()
    (destination / "keep.txt").write_text("do not overwrite\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "--file",
            str(ciphertext),
            "--into",
            str(destination),
            "--identity-file",
            str(identity),
        ],
    )

    assert result.exit_code == 1
    assert "destination must be empty" in result.output
    assert (destination / "keep.txt").read_text() == "do not overwrite\n"


def test_offline_restore_rejects_tampered_ciphertext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.main import app

    ciphertext, identity, _checksum = _encrypted_project_backup(tmp_path, monkeypatch)
    content = bytearray(ciphertext.read_bytes())
    content[len(content) // 2] ^= 0x01
    ciphertext.write_bytes(content)

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "--file",
            str(ciphertext),
            "--into",
            str(tmp_path / "recovered"),
            "--identity-file",
            str(identity),
        ],
    )

    assert result.exit_code == 1
    assert "age decryption failed" in result.output


def test_offline_restore_decrypts_the_exact_ciphertext_bytes_that_were_hashed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import backup_runtime
    from cli.main import app

    ciphertext, identity, checksum = _encrypted_project_backup(tmp_path, monkeypatch)
    decrypt = backup_runtime.decrypt_offsite_archive

    def replace_source_after_staging(
        staged_ciphertext: Path,
        plaintext: Path,
        identity_file: Path,
    ) -> dict[str, str]:
        assert staged_ciphertext != ciphertext
        ciphertext.write_bytes(b"replaced after private staging")
        return decrypt(staged_ciphertext, plaintext, identity_file)

    monkeypatch.setattr(
        backup_runtime,
        "decrypt_offsite_archive",
        replace_source_after_staging,
    )
    destination = tmp_path / "recovered"

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "--file",
            str(ciphertext),
            "--into",
            str(destination),
            "--identity-file",
            str(identity),
            "--expected-checksum",
            checksum,
        ],
    )

    assert result.exit_code == 0, result.output
    assert _git(destination, "rev-list", "--count", "HEAD").stdout.strip() == "2"
    assert "Ciphertext SHA-256 matched" in result.output


def test_offline_restore_rejects_invalid_or_mismatched_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.main import app

    ciphertext, identity, _checksum = _encrypted_project_backup(tmp_path, monkeypatch)
    base_args = [
        "backup",
        "restore",
        "--file",
        str(ciphertext),
        "--into",
        str(tmp_path / "recovered"),
        "--identity-file",
        str(identity),
        "--expected-checksum",
    ]

    invalid = runner.invoke(app, [*base_args, "not-a-checksum"])
    mismatched = runner.invoke(app, [*base_args, "sha256:" + "0" * 64])

    assert invalid.exit_code == 1
    assert "sha256:<64 lowercase hex characters>" in invalid.output
    assert mismatched.exit_code == 1
    assert "Ciphertext checksum mismatch" in mismatched.output


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["backup-1", "--identity-file", "saved.agekey"], "cannot use a backup ID"),
        (
            ["--expected-checksum", "sha256:" + "0" * 64],
            "requires --identity-file",
        ),
    ],
)
def test_offline_flags_cannot_weaken_normal_id_restore(
    tmp_path: Path,
    extra_args: list[str],
    message: str,
) -> None:
    from cli.main import app

    archive = tmp_path / "backup.tar.gz.age"
    archive.write_bytes(b"ciphertext")
    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            *extra_args,
            "--file",
            str(archive),
            "--into",
            str(tmp_path / "recovered"),
        ],
    )

    assert result.exit_code == 1
    assert message in result.output
