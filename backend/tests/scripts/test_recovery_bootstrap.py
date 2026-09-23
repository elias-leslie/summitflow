from __future__ import annotations

import hashlib
import io
import json
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


def _parts_manifest(
    tmp_path: Path,
    chunks: list[bytes],
    *,
    archive_name: str = "summitflow-20260921-120000.tar.gz.age",
) -> tuple[Path, bytes]:
    archive = b"".join(chunks)
    parts = []
    for index, chunk in enumerate(chunks, start=1):
        name = f"{archive_name}.part{index:06d}"
        (tmp_path / name).write_bytes(chunk)
        parts.append(
            {
                "name": name,
                "size_bytes": len(chunk),
                "checksum": f"sha256:{hashlib.sha256(chunk).hexdigest()}",
            }
        )
    manifest = {
        "version": 1,
        "format": "summitflow-age-parts",
        "archive_name": archive_name,
        "size_bytes": len(archive),
        "checksum": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "parts": parts,
    }
    path = tmp_path / f"{archive_name}.parts.json"
    path.write_text(json.dumps(manifest))
    return path, archive


def _assemble(manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--assemble-parts",
            str(manifest),
            "--output-file",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_assemble_parts_reproduces_ordered_ciphertext(tmp_path: Path) -> None:
    manifest, archive = _parts_manifest(tmp_path, [b"age-header\n", b"payload", b"-end"])
    output = tmp_path / "summitflow-20260921-120000.tar.gz.age"

    result = _assemble(manifest, output)

    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == archive
    assert output.stat().st_mode & 0o777 == 0o600
    assert f"ASSEMBLY_READY {output}" in result.stdout


def test_assembled_ciphertext_is_accepted_by_normal_bootstrap(tmp_path: Path) -> None:
    identity, recipient = _age_identity(tmp_path, "recovery")
    encrypted, checksum = _encrypted_archive(tmp_path, recipient)
    ciphertext = encrypted.read_bytes()
    encrypted.unlink()
    manifest, _archive = _parts_manifest(
        tmp_path,
        [ciphertext[: len(ciphertext) // 2], ciphertext[len(ciphertext) // 2 :]],
    )
    assembled = tmp_path / "summitflow-20260921-120000.tar.gz.age"

    assembly_result = _assemble(manifest, assembled)
    destination = tmp_path / "bootstrap"
    bootstrap_result = _run(assembled, identity, destination, checksum)

    assert assembly_result.returncode == 0, assembly_result.stderr
    assert bootstrap_result.returncode == 0, bootstrap_result.stderr
    assert (destination / "summitflow/backend/pyproject.toml").is_file()


@pytest.mark.parametrize("failure", ["missing", "checksum"])
def test_assemble_parts_rejects_missing_or_wrong_part_and_cleans_output(
    tmp_path: Path,
    failure: str,
) -> None:
    manifest, _archive = _parts_manifest(tmp_path, [b"first", b"second"])
    second = tmp_path / "summitflow-20260921-120000.tar.gz.age.part000002"
    if failure == "missing":
        second.unlink()
    else:
        second.write_bytes(b"tampered")
    output = tmp_path / "summitflow-20260921-120000.tar.gz.age"

    result = _assemble(manifest, output)

    assert result.returncode == 1
    assert not output.exists()
    assert not list(tmp_path.glob(f".{output.name}.*"))


def test_assemble_parts_rejects_declared_size_mismatch_before_copy(
    tmp_path: Path,
) -> None:
    manifest, _archive = _parts_manifest(tmp_path, [b"declared", b"second"])
    content = json.loads(manifest.read_text())
    content["parts"][0]["size_bytes"] -= 1
    content["size_bytes"] -= 1
    manifest.write_text(json.dumps(content))
    output = tmp_path / "summitflow-20260921-120000.tar.gz.age"

    result = _assemble(manifest, output)

    assert result.returncode == 1
    assert "size does not match manifest before assembly" in result.stderr
    assert not output.exists()
    assert not list(tmp_path.glob(f".{output.name}.*"))


@pytest.mark.parametrize(
    ("field", "unsafe_name"),
    [
        ("archive_name", "../escape.tar.gz.age"),
        ("part_name", "../escape.tar.gz.age.part000001"),
    ],
)
def test_assemble_parts_rejects_traversal_names(
    tmp_path: Path,
    field: str,
    unsafe_name: str,
) -> None:
    manifest, _archive = _parts_manifest(tmp_path, [b"ciphertext"])
    content = json.loads(manifest.read_text())
    if field == "archive_name":
        content["archive_name"] = unsafe_name
    else:
        content["parts"][0]["name"] = unsafe_name
    manifest.write_text(json.dumps(content))
    output = tmp_path / "summitflow-20260921-120000.tar.gz.age"

    result = _assemble(manifest, output)

    assert result.returncode == 1
    assert "unsafe" in result.stderr
    assert not output.exists()


def test_assemble_parts_refuses_to_overwrite_output(tmp_path: Path) -> None:
    manifest, _archive = _parts_manifest(tmp_path, [b"ciphertext"])
    output = tmp_path / "summitflow-20260921-120000.tar.gz.age"
    output.write_bytes(b"preserve me")

    result = _assemble(manifest, output)

    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert output.read_bytes() == b"preserve me"


@pytest.mark.parametrize("link_kind", ["symbolic", "hard"])
def test_assemble_parts_rejects_linked_parts(tmp_path: Path, link_kind: str) -> None:
    manifest, _archive = _parts_manifest(tmp_path, [b"ciphertext"])
    part = tmp_path / "summitflow-20260921-120000.tar.gz.age.part000001"
    original = tmp_path / "linked-content"
    part.replace(original)
    if link_kind == "symbolic":
        part.symlink_to(original)
    else:
        part.hardlink_to(original)
    output = tmp_path / "summitflow-20260921-120000.tar.gz.age"

    result = _assemble(manifest, output)

    assert result.returncode == 1
    assert "not a regular file" in result.stderr
    assert not output.exists()


def test_assemble_parts_rejects_wrong_manifest_contract(tmp_path: Path) -> None:
    manifest, _archive = _parts_manifest(tmp_path, [b"ciphertext"])
    content = json.loads(manifest.read_text())
    content["format"] = "some-other-format"
    manifest.write_text(json.dumps(content))
    output = tmp_path / "summitflow-20260921-120000.tar.gz.age"

    result = _assemble(manifest, output)

    assert result.returncode == 1
    assert "manifest" in result.stderr
    assert not output.exists()


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
