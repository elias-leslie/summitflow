#!/usr/bin/env python3
"""Unlock SummitFlow source from an encrypted native backup without ST."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

MINIMUM_PYTHON = (3, 12)
CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
ARCHIVE_ROOT = "summitflow"
DATABASE_MEMBER = "summitflow/database.sql.gz"
REQUIRED_SOURCE_MEMBER = "summitflow/backend/pyproject.toml"


class BootstrapError(RuntimeError):
    """A safe, user-facing bootstrap failure."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract SummitFlow source from an encrypted native backup. "
            "Requires Python 3.12+ and age; does not install or restore services/databases."
        )
    )
    parser.add_argument("archive", type=Path, help="SummitFlow .tar.gz.age archive")
    parser.add_argument(
        "--identity-file",
        required=True,
        type=Path,
        help="Saved age identity file",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Absent or empty destination populated with summitflow/",
    )
    parser.add_argument(
        "--expected-sha256",
        help="Optional recorded ciphertext checksum as sha256:<64 lowercase hex>",
    )
    return parser.parse_args(argv)


def _validate_inputs(
    archive: Path,
    identity_file: Path,
    destination: Path,
    expected_checksum: str | None,
) -> None:
    if sys.version_info < MINIMUM_PYTHON:
        raise BootstrapError("Python 3.12 or newer is required")
    if not archive.is_file():
        raise BootstrapError("encrypted archive is not a regular file")
    if not identity_file.is_file():
        raise BootstrapError("saved age identity is not a regular file")
    if destination.is_symlink():
        raise BootstrapError("output directory cannot be a symbolic link")
    if destination.exists():
        if not destination.is_dir():
            raise BootstrapError("output path exists and is not a directory")
        if any(destination.iterdir()):
            raise BootstrapError("output directory must be empty")
    if not destination.parent.is_dir():
        raise BootstrapError("output directory parent must already exist")
    if expected_checksum is not None and CHECKSUM_PATTERN.fullmatch(
        expected_checksum.strip()
    ) is None:
        raise BootstrapError(
            "expected checksum must use sha256:<64 lowercase hex characters>"
        )
    if shutil.which("age") is None:
        raise BootstrapError("age executable was not found")


def _copy_and_hash(source: Path, destination: Path) -> str:
    digest = hashlib.sha256()
    destination.touch(mode=0o600, exist_ok=False)
    with source.open("rb") as input_file, destination.open("wb") as output_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
            output_file.write(chunk)
    return f"sha256:{digest.hexdigest()}"


def _decrypt(ciphertext: Path, identity_file: Path, plaintext: Path) -> None:
    try:
        result = subprocess.run(
            [
                "age",
                "--decrypt",
                "--identity",
                str(identity_file),
                "--output",
                str(plaintext),
                str(ciphertext),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise BootstrapError("age decryption could not start") from exc
    if result.returncode != 0:
        raise BootstrapError("age decryption failed")
    plaintext.chmod(0o600)


def _validated_source_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    roots: set[str] = set()
    source_members: list[tarfile.TarInfo] = []
    required_source_found = False
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise BootstrapError("archive contains an unsafe path")
        roots.add(path.parts[0])
        if member.islnk() or not (member.isdir() or member.isreg() or member.issym()):
            raise BootstrapError("archive contains a device, hard link, or unsupported member")
        if path.as_posix() == DATABASE_MEMBER:
            continue
        if path.as_posix() == REQUIRED_SOURCE_MEMBER and member.isreg():
            required_source_found = True
        source_members.append(member)
    if roots != {ARCHIVE_ROOT}:
        raise BootstrapError("archive must contain exactly the summitflow root")
    if not required_source_found:
        raise BootstrapError("archive does not contain SummitFlow backend source")
    return source_members


def _extract_source(plaintext: Path, payload_dir: Path) -> None:
    try:
        with tarfile.open(plaintext, "r:gz") as archive:
            members = _validated_source_members(archive)
            archive.extractall(payload_dir, members=members, filter="data")
    except BootstrapError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise BootstrapError("archive validation or extraction failed") from exc


def _publish_payload(payload_dir: Path, destination: Path) -> None:
    destination_existed = destination.exists()
    if destination_existed:
        try:
            destination.rmdir()
        except OSError as exc:
            raise BootstrapError("output directory stopped being empty") from exc
    try:
        os.replace(payload_dir, destination)
    except OSError as exc:
        if destination_existed and not destination.exists():
            destination.mkdir(mode=0o700)
        raise BootstrapError("could not publish extracted source") from exc


def bootstrap(args: argparse.Namespace) -> Path:
    archive = args.archive.expanduser().absolute()
    identity_file = args.identity_file.expanduser().absolute()
    destination = args.output_dir.expanduser().absolute()
    expected_checksum = args.expected_sha256
    _validate_inputs(archive, identity_file, destination, expected_checksum)

    with tempfile.TemporaryDirectory(
        prefix=".summitflow-recovery-",
        dir=destination.parent,
    ) as temporary:
        private_dir = Path(temporary)
        ciphertext = private_dir / "summitflow.tar.gz.age"
        plaintext = private_dir / "summitflow.tar.gz"
        payload = private_dir / "payload"
        payload.mkdir(mode=0o700)
        actual_checksum = _copy_and_hash(archive, ciphertext)
        if expected_checksum is not None and not hmac.compare_digest(
            actual_checksum,
            expected_checksum.strip(),
        ):
            raise BootstrapError("ciphertext checksum mismatch")
        _decrypt(ciphertext, identity_file, plaintext)
        _extract_source(plaintext, payload)
        _publish_payload(payload, destination)
    return destination / ARCHIVE_ROOT


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = _parse_args(argv)
    try:
        source_root = bootstrap(args)
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    backend = source_root / "backend"
    print(f"SOURCE_READY {source_root}")
    print(f"NEXT: cd {shlex.quote(str(backend))} && uv sync --frozen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
