from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "recovery-bootstrap.py"


def _age_identity(tmp_path: Path, name: str) -> tuple[Path, str]:
    identity = tmp_path / f"{name}.agekey"
    subprocess.run(
        ["age-keygen", "-o", str(identity)],
        capture_output=True,
        text=True,
        check=True,
    )
    recipient = subprocess.run(
        ["age-keygen", "-y", str(identity)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return identity, recipient


def _encrypted_archive(
    tmp_path: Path,
    recipient: str,
    *,
    unsafe_member: str | None = None,
    unsupported_type: bytes | None = None,
) -> tuple[Path, str]:
    plaintext = tmp_path / "summitflow.tar.gz"
    with tarfile.open(plaintext, "w:gz") as archive:
        files = {
            "summitflow/backend/pyproject.toml": b"[project]\nname='summitflow'\n",
            "summitflow/backend/cli/main.py": b"app = object()\n",
            "summitflow/database.sql.gz": b"database dump must not be bootstrapped\n",
        }
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        if unsafe_member is not None:
            member = tarfile.TarInfo(unsafe_member)
            member.size = 6
            archive.addfile(member, io.BytesIO(b"unsafe"))
        if unsupported_type is not None:
            member = tarfile.TarInfo("summitflow/unsupported")
            member.type = unsupported_type
            if unsupported_type == tarfile.LNKTYPE:
                member.linkname = "summitflow/backend/pyproject.toml"
            archive.addfile(member)
    ciphertext = tmp_path / "summitflow.tar.gz.age"
    subprocess.run(
        ["age", "--recipient", recipient, "--output", str(ciphertext), str(plaintext)],
        capture_output=True,
        text=True,
        check=True,
    )
    checksum = f"sha256:{hashlib.sha256(ciphertext.read_bytes()).hexdigest()}"
    return ciphertext, checksum


def _run(
    archive: Path,
    identity: Path,
    destination: Path,
    checksum: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        str(archive),
        "--identity-file",
        str(identity),
        "--output-dir",
        str(destination),
    ]
    if checksum is not None:
        command.extend(["--expected-sha256", checksum])
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_valid_bootstrap_extracts_source_only_and_prints_next_command(tmp_path: Path) -> None:
    identity, recipient = _age_identity(tmp_path, "recovery")
    archive, checksum = _encrypted_archive(tmp_path, recipient)
    destination = tmp_path / "bootstrap"
    destination.mkdir()

    result = _run(archive, identity, destination, checksum)

    assert result.returncode == 0, result.stderr
    assert (destination / "summitflow/backend/pyproject.toml").is_file()
    assert not (destination / "summitflow/database.sql.gz").exists()
    assert f"SOURCE_READY {destination}/summitflow" in result.stdout
    assert f"NEXT: cd {destination}/summitflow/backend && uv sync --frozen" in result.stdout
    assert "AGE-SECRET-KEY" not in result.stdout + result.stderr


def test_wrong_key_leaves_destination_absent(tmp_path: Path) -> None:
    _identity, recipient = _age_identity(tmp_path, "encrypt")
    wrong_identity, _wrong_recipient = _age_identity(tmp_path, "wrong")
    archive, _checksum = _encrypted_archive(tmp_path, recipient)
    destination = tmp_path / "bootstrap"

    result = _run(archive, wrong_identity, destination)

    assert result.returncode == 1
    assert "age decryption failed" in result.stderr
    assert not destination.exists()


def test_tampered_ciphertext_leaves_destination_absent(tmp_path: Path) -> None:
    identity, recipient = _age_identity(tmp_path, "recovery")
    archive, _checksum = _encrypted_archive(tmp_path, recipient)
    content = bytearray(archive.read_bytes())
    content[len(content) // 2] ^= 1
    archive.write_bytes(content)
    destination = tmp_path / "bootstrap"

    result = _run(archive, identity, destination)

    assert result.returncode == 1
    assert "age decryption failed" in result.stderr
    assert not destination.exists()


def test_mismatched_recorded_checksum_fails_before_extraction(tmp_path: Path) -> None:
    identity, recipient = _age_identity(tmp_path, "recovery")
    archive, _checksum = _encrypted_archive(tmp_path, recipient)
    destination = tmp_path / "bootstrap"

    result = _run(archive, identity, destination, "sha256:" + "0" * 64)

    assert result.returncode == 1
    assert "ciphertext checksum mismatch" in result.stderr
    assert not destination.exists()


def test_nonempty_destination_is_unchanged(tmp_path: Path) -> None:
    identity, recipient = _age_identity(tmp_path, "recovery")
    archive, _checksum = _encrypted_archive(tmp_path, recipient)
    destination = tmp_path / "bootstrap"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("preserve me\n")

    result = _run(archive, identity, destination)

    assert result.returncode == 1
    assert "output directory must be empty" in result.stderr
    assert sentinel.read_text() == "preserve me\n"


@pytest.mark.parametrize(
    "unsafe_member",
    ["summitflow/../../escape.txt", "other-root/file.txt"],
)
def test_unsafe_or_wrong_root_archive_is_rejected_without_destination(
    tmp_path: Path,
    unsafe_member: str,
) -> None:
    identity, recipient = _age_identity(tmp_path, "recovery")
    archive, _checksum = _encrypted_archive(
        tmp_path,
        recipient,
        unsafe_member=unsafe_member,
    )
    destination = tmp_path / "bootstrap"

    result = _run(archive, identity, destination)

    assert result.returncode == 1
    assert not destination.exists()
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("member_type", [tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_hard_link_or_device_member_is_rejected(
    tmp_path: Path,
    member_type: bytes,
) -> None:
    identity, recipient = _age_identity(tmp_path, "recovery")
    archive, _checksum = _encrypted_archive(
        tmp_path,
        recipient,
        unsupported_type=member_type,
    )
    destination = tmp_path / "bootstrap"

    result = _run(archive, identity, destination)

    assert result.returncode == 1
    assert "device, hard link, or unsupported member" in result.stderr
    assert not destination.exists()
