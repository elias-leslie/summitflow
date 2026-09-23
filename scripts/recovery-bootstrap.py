#!/usr/bin/env python3
"""Unlock SummitFlow source from an encrypted native backup without ST."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

MINIMUM_PYTHON = (3, 12)
CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
SAFE_ARCHIVE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz\.age")
PARTS_FORMAT = "summitflow-age-parts"
PARTS_VERSION = 1
MAX_MANIFEST_BYTES = 1024 * 1024
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
    parser.add_argument(
        "archive",
        nargs="?",
        type=Path,
        help="SummitFlow .tar.gz.age archive",
    )
    parser.add_argument(
        "--identity-file",
        type=Path,
        help="Saved age identity file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Absent or empty destination populated with summitflow/",
    )
    parser.add_argument(
        "--expected-sha256",
        help="Optional recorded ciphertext checksum as sha256:<64 lowercase hex>",
    )
    parser.add_argument(
        "--assemble-parts",
        type=Path,
        help="Assemble a summitflow-age-parts manifest without decrypting it",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Absent destination for the reassembled .tar.gz.age archive",
    )
    args = parser.parse_args(argv)
    if args.assemble_parts is not None:
        if args.archive is not None or args.identity_file is not None or args.output_dir is not None:
            parser.error(
                "--assemble-parts cannot be combined with archive, --identity-file, or --output-dir"
            )
        if args.expected_sha256 is not None:
            parser.error("the parts manifest supplies the expected archive checksum")
        if args.output_file is None:
            parser.error("--assemble-parts requires --output-file")
    else:
        if args.archive is None or args.identity_file is None or args.output_dir is None:
            parser.error("archive, --identity-file, and --output-dir are required")
        if args.output_file is not None:
            parser.error("--output-file requires --assemble-parts")
    return args


def _open_regular_nofollow(path: Path, description: str):
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BootstrapError(f"{description} is missing or is not a regular file") from exc
    try:
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode) or file_status.st_nlink != 1:
            raise BootstrapError(f"{description} is missing or is not a regular file")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _read_parts_manifest(path: Path) -> dict[str, object]:
    with _open_regular_nofollow(path, "parts manifest") as manifest_file:
        raw = manifest_file.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise BootstrapError("parts manifest is too large")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("parts manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise BootstrapError("parts manifest has an invalid contract")
    return manifest


def _manifest_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _validate_parts_manifest(
    manifest: dict[str, object],
    manifest_path: Path,
    output: Path,
) -> tuple[str, int, str, list[dict[str, object]]]:
    if set(manifest) != {
        "version",
        "format",
        "archive_name",
        "size_bytes",
        "checksum",
        "parts",
    }:
        raise BootstrapError("parts manifest has an invalid contract")
    archive_name = manifest.get("archive_name")
    checksum = manifest.get("checksum")
    parts = manifest.get("parts")
    if (
        manifest.get("version") != PARTS_VERSION
        or type(manifest.get("version")) is not int
        or manifest.get("format") != PARTS_FORMAT
        or not isinstance(archive_name, str)
        or SAFE_ARCHIVE_NAME_PATTERN.fullmatch(archive_name) is None
        or not _manifest_integer(manifest.get("size_bytes"))
        or not isinstance(checksum, str)
        or CHECKSUM_PATTERN.fullmatch(checksum) is None
        or not isinstance(parts, list)
        or not parts
    ):
        raise BootstrapError("parts manifest has an invalid contract or unsafe name")
    if manifest_path.name != f"{archive_name}.parts.json":
        raise BootstrapError("parts manifest has an unsafe or mismatched filename")
    if output.name != archive_name:
        raise BootstrapError("output filename must match the manifest archive name")

    validated_parts: list[dict[str, object]] = []
    declared_total = 0
    for index, part in enumerate(parts, start=1):
        expected_name = f"{archive_name}.part{index:06d}"
        if (
            not isinstance(part, dict)
            or set(part) != {"name", "size_bytes", "checksum"}
            or part.get("name") != expected_name
            or not _manifest_integer(part.get("size_bytes"))
            or not isinstance(part.get("checksum"), str)
            or CHECKSUM_PATTERN.fullmatch(part["checksum"]) is None
        ):
            raise BootstrapError("parts manifest has an invalid contract or unsafe part name")
        declared_total += part["size_bytes"]
        validated_parts.append(part)
    if declared_total != manifest["size_bytes"]:
        raise BootstrapError("parts manifest size does not match its part sizes")
    return archive_name, manifest["size_bytes"], checksum, validated_parts


def assemble_parts(manifest_path: Path, output: Path) -> Path:
    if sys.version_info < MINIMUM_PYTHON:
        raise BootstrapError("Python 3.12 or newer is required")
    manifest_path = manifest_path.expanduser().absolute()
    output = output.expanduser().absolute()
    if output.is_symlink() or output.exists():
        raise BootstrapError("output file already exists")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise BootstrapError("output file parent must be an existing real directory")

    manifest = _read_parts_manifest(manifest_path)
    _archive_name, expected_size, expected_checksum, parts = _validate_parts_manifest(
        manifest,
        manifest_path,
        output,
    )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    archive_digest = hashlib.sha256()
    archive_size = 0
    try:
        os.fchmod(descriptor, 0o600)
        assembled_file = os.fdopen(descriptor, "wb")
        descriptor = -1
        with assembled_file as assembled:
            for part in parts:
                part_path = manifest_path.parent / part["name"]
                part_digest = hashlib.sha256()
                part_size = 0
                with _open_regular_nofollow(part_path, f"archive part {part['name']}") as source:
                    expected_part_size = part["size_bytes"]
                    if os.fstat(source.fileno()).st_size != expected_part_size:
                        raise BootstrapError(
                            f"archive part {part['name']} size does not match manifest before assembly"
                        )
                    remaining = expected_part_size
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise BootstrapError(
                                f"archive part {part['name']} changed size during assembly"
                            )
                        assembled.write(chunk)
                        archive_digest.update(chunk)
                        part_digest.update(chunk)
                        archive_size += len(chunk)
                        part_size += len(chunk)
                        remaining -= len(chunk)
                    if source.read(1) or os.fstat(source.fileno()).st_size != expected_part_size:
                        raise BootstrapError(
                            f"archive part {part['name']} changed size during assembly"
                        )
                actual_part_checksum = f"sha256:{part_digest.hexdigest()}"
                if part_size != part["size_bytes"] or not hmac.compare_digest(
                    actual_part_checksum,
                    part["checksum"],
                ):
                    raise BootstrapError(f"archive part {part['name']} failed verification")
            assembled.flush()
            os.fsync(assembled.fileno())
        actual_checksum = f"sha256:{archive_digest.hexdigest()}"
        if archive_size != expected_size or not hmac.compare_digest(
            actual_checksum,
            expected_checksum,
        ):
            raise BootstrapError("reassembled archive failed verification")
        try:
            os.link(temporary, output, follow_symlinks=False)
        except FileExistsError as exc:
            raise BootstrapError("output file already exists") from exc
        except OSError as exc:
            raise BootstrapError("could not publish reassembled archive") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return output


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
        if args.assemble_parts is not None:
            output = assemble_parts(args.assemble_parts, args.output_file)
            print(f"ASSEMBLY_READY {output}")
            return 0
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
