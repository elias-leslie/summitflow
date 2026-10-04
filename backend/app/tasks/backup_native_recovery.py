"""Portable, consistent recovery payloads for native project backups."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from ..services.backup_keys import backup_key_directory
from .backup_activity import BackupCancelled, backup_phase, check_backup_cancelled, run_bulk_process

RECOVERY_DIR_NAME = ".summitflow-recovery"
RECOVERY_MANIFEST_NAME = "manifest.json"
GIT_BUNDLE_NAME = "git.bundle"
GIT_INDEX_NAME = "git-index"
GIT_SHARED_INDEX_NAME = "git-shared-index"
GIT_RECOVERY_FORMAT = 1
ST_METADATA_DIR_NAME = "st-metadata"
ST_METADATA_ROOTS = ("st/acceptance", "st/native-stages", "st/publication", "st-publication")
SQLITE_TRANSIENT_SUFFIXES = ("-wal", "-shm", "-journal")
JJ_GIT_IMPORT_EXPORT_LOCK = ".jj/repo/git_import_export.lock"


@dataclass(frozen=True)
class SnapshotEntry:
    """Source metadata used to detect concurrent tree changes."""

    kind: str
    mode: int
    size: int
    mtime_ns: int
    inode: int
    link_target: str | None = None
    sqlite_database: bool = False
    append_only_jsonl: bool = False
    point_in_time_json: bool = False
    target_source: str | None = None
    target_relative_path: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            check_backup_cancelled()
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _safe_relative_symlink(path: Path, project_dir: Path, link_target: str) -> bool:
    target = PurePosixPath(link_target)
    if not link_target or "\x00" in link_target or "\\" in link_target or target.is_absolute():
        return False
    candidate = (path.parent / Path(*target.parts)).resolve(strict=False)
    return candidate.is_relative_to(project_dir.resolve())


def inventory_project_tree(
    project_dir: Path,
    excludes: tuple[str, ...],
    should_exclude: Any,
    *,
    source_roots: dict[str, Path] | None = None,
    sensitive_paths: tuple[Path, ...] = (),
) -> dict[str, SnapshotEntry]:
    """Inventory included regular files and safe in-tree relative symlinks."""
    inventory: dict[str, SnapshotEntry] = {}
    backup_phase("inventory")
    root_metadata = project_dir.lstat()
    if stat.S_ISREG(root_metadata.st_mode):
        if not should_exclude(project_dir.name, excludes):
            inventory[project_dir.name] = _regular_entry(project_dir, root_metadata)
        return inventory
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise RuntimeError("Backup source must be a directory or explicit regular file")

    def walk_error(error: OSError) -> None:
        raise error

    for root, dirs, files in os.walk(project_dir, followlinks=False, onerror=walk_error):
        check_backup_cancelled()
        root_path = Path(root)
        rel_root = root_path.relative_to(project_dir).as_posix()
        rel_root = "" if rel_root == "." else rel_root
        retained_dirs: list[str] = []
        for dirname in dirs:
            path = root_path / dirname
            rel = (Path(rel_root) / dirname).as_posix()
            if should_exclude(rel, excludes):
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                _record_symlink(inventory, path, rel, project_dir, source_roots, sensitive_paths)
            elif stat.S_ISDIR(mode):
                retained_dirs.append(dirname)
        dirs[:] = retained_dirs

        sqlite_databases: set[str] = set()
        for filename in files:
            check_backup_cancelled()
            path = root_path / filename
            rel = (Path(rel_root) / filename).as_posix()
            if should_exclude(rel, excludes):
                continue
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(metadata.st_mode) and _is_sqlite_database(path):
                sqlite_databases.add(filename)

        for filename in files:
            check_backup_cancelled()
            path = root_path / filename
            rel = (Path(rel_root) / filename).as_posix()
            if should_exclude(rel, excludes):
                continue
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                if _is_sqlite_transient_file(path, sqlite_databases):
                    continue
                raise RuntimeError(f"Backup source changed during inventory: {rel}") from None
            if stat.S_ISLNK(metadata.st_mode):
                _record_symlink(inventory, path, rel, project_dir, source_roots, sensitive_paths)
            elif stat.S_ISREG(metadata.st_mode):
                if rel == JJ_GIT_IMPORT_EXPORT_LOCK and metadata.st_size == 0:
                    continue
                if _is_sqlite_transient_file(path, sqlite_databases):
                    continue
                sqlite_database = filename in sqlite_databases
                inventory[rel] = SnapshotEntry(
                    kind="file",
                    mode=stat.S_IMODE(metadata.st_mode),
                    # An online SQLite backup is transactionally consistent even
                    # while a writer advances WAL or checkpoints the main file.
                    # Retain identity and permissions checks, but do not treat
                    # legitimate database size/mtime churn as an unrelated edit.
                    size=0 if sqlite_database else metadata.st_size,
                    mtime_ns=0 if sqlite_database else metadata.st_mtime_ns,
                    inode=metadata.st_ino,
                    sqlite_database=sqlite_database,
                    append_only_jsonl=not sqlite_database and path.suffix.lower() == ".jsonl",
                    # Desktop bookkeeping changes independently of conversation
                    # payloads. Keep a stable, validated copy rather than
                    # requiring it to remain untouched throughout a long tree
                    # capture. No general JSON or source-edit exception.
                    point_in_time_json=project_dir.name == ".codex" and rel in {
                        ".codex-global-state.json", ".codex-global-state.json.bak",
                    },
                )
    return inventory


def _regular_entry(path: Path, metadata: os.stat_result) -> SnapshotEntry:
    sqlite_database = _is_sqlite_database(path)
    return SnapshotEntry(
        kind="file", mode=stat.S_IMODE(metadata.st_mode),
        size=0 if sqlite_database else metadata.st_size,
        mtime_ns=0 if sqlite_database else metadata.st_mtime_ns,
        inode=metadata.st_ino, sqlite_database=sqlite_database,
        append_only_jsonl=not sqlite_database and path.suffix.lower() == ".jsonl",
    )


def _record_symlink(
    inventory: dict[str, SnapshotEntry],
    path: Path,
    rel: str,
    project_dir: Path,
    source_roots: dict[str, Path] | None = None,
    sensitive_paths: tuple[Path, ...] = (),
) -> None:
    metadata = path.lstat()
    target = os.readlink(path)
    if not target or "\x00" in target or "\\" in target:
        return
    if not _safe_relative_symlink(path, project_dir, target):
        candidate = (path.parent / target).resolve(strict=False)
        if any(candidate.is_relative_to(root.expanduser().resolve(strict=False)) for root in (*sensitive_paths, backup_key_directory())):
            return
        for source_name, source_root in sorted((source_roots or {}).items()):
            # A registration names an actual canonical source, never a link to
            # one. Merely recording a link must not read its target's contents.
            source_root = source_root.expanduser()
            if source_root.is_symlink():
                continue
            canonical = source_root.resolve(strict=False)
            if candidate == canonical or (source_root.is_dir() and candidate.is_relative_to(canonical)):
                inventory[rel] = SnapshotEntry(
                    kind="mapped_link", mode=stat.S_IMODE(metadata.st_mode),
                    size=metadata.st_size, mtime_ns=metadata.st_mtime_ns,
                    inode=metadata.st_ino, link_target=target,
                    target_source=source_name,
                    target_relative_path=candidate.relative_to(canonical).as_posix(),
                )
                break
        return
    inventory[rel] = SnapshotEntry(
        kind="symlink",
        mode=stat.S_IMODE(metadata.st_mode),
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        inode=metadata.st_ino,
        link_target=target,
    )


def _is_sqlite_database(path: Path) -> bool:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return False
            return source.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _is_sqlite_transient_file(
    path: Path,
    sqlite_databases: set[str],
) -> bool:
    """Return whether path is a standard sidecar for a recognized SQLite DB."""
    for suffix in SQLITE_TRANSIENT_SUFFIXES:
        if path.name.endswith(suffix):
            database_name = path.name[: -len(suffix)]
            return database_name in sqlite_databases
    return False


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    check_backup_cancelled()
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_db, sqlite3.connect(destination) as destination_db:
        page_size = int(source_db.execute("PRAGMA page_size").fetchone()[0])
        source_db.backup(
            destination_db,
            pages=max(1, (1024 * 1024) // page_size),
            progress=lambda _status, _remaining, _total: check_backup_cancelled(),
        )
    shutil.copystat(source, destination, follow_symlinks=False)


def copy_inventory_snapshot(
    project_dir: Path,
    destination: Path,
    inventory: dict[str, SnapshotEntry],
) -> None:
    """Copy exactly one inventory without following links or special files."""
    backup_phase("snapshot")
    destination.mkdir(parents=True, exist_ok=True)
    for rel, entry in sorted(inventory.items()):
        check_backup_cancelled()
        source = project_dir if project_dir.is_file() else project_dir / Path(*PurePosixPath(rel).parts)
        target = destination / Path(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.kind == "mapped_link":
            continue  # External links are identities in the manifest only.
        if entry.kind == "symlink":
            target.symlink_to(entry.link_target or "")
        elif entry.sqlite_database:
            _copy_sqlite_database(source, target)
        elif entry.append_only_jsonl:
            _copy_jsonl_prefix(source, target, entry, rel)
        else:
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as input_file, target.open("xb") as output_file:
                if not _regular_identity_matches(os.fstat(input_file.fileno()), entry):
                    raise RuntimeError(f"Backup source changed during capture: {rel}")
                while True:
                    check_backup_cancelled()
                    chunk = input_file.read(1024 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)
                if not _regular_identity_matches(os.fstat(input_file.fileno()), entry):
                    raise RuntimeError(f"Backup source changed during capture: {rel}")
            shutil.copystat(source, target, follow_symlinks=False)
            if entry.point_in_time_json:
                try:
                    with target.open() as captured_json:
                        if not isinstance(json.load(captured_json), dict):
                            raise ValueError("Expected desktop state object")
                except (OSError, ValueError):
                    raise RuntimeError(f"Invalid point-in-time JSON snapshot: {rel}") from None


def _regular_identity_matches(metadata: os.stat_result, entry: SnapshotEntry) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == entry.mode
        and metadata.st_ino == entry.inode
        and metadata.st_size == entry.size
        and metadata.st_mtime_ns == entry.mtime_ns
    )


def _copy_jsonl_prefix(
    source: Path,
    destination: Path,
    entry: SnapshotEntry,
    relative_path: str,
) -> None:
    """Copy the raw point-in-time prefix inventoried for an append-only log.

    The prefix is deliberately not parsed: a writer may have an in-flight final
    record, and recovery preserves those exact bytes without reading a growing
    tail indefinitely.
    """
    try:
        metadata = source.lstat()
        if not _jsonl_identity_matches(metadata, entry):
            raise RuntimeError
        remaining = entry.size
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            if not _jsonl_identity_matches(os.fstat(input_file.fileno()), entry):
                raise RuntimeError
            while remaining:
                check_backup_cancelled()
                chunk = input_file.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError
                output_file.write(chunk)
                remaining -= len(chunk)
            if not _jsonl_identity_matches(os.fstat(input_file.fileno()), entry):
                raise RuntimeError
        shutil.copystat(source, destination, follow_symlinks=False)
    except BackupCancelled:
        raise
    except (OSError, RuntimeError):
        raise RuntimeError(
            f"Backup source changed during capture: {relative_path}"
        ) from None


def _jsonl_identity_matches(metadata: os.stat_result, entry: SnapshotEntry) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == entry.mode
        and metadata.st_ino == entry.inode
        and metadata.st_size >= entry.size
    )


def _jsonl_prefix_matches(
    source: Path,
    captured: Path,
    entry: SnapshotEntry,
) -> bool:
    """Confirm the source still begins with the exact captured raw prefix."""
    try:
        if captured.stat().st_size != entry.size:
            return False
        with source.open("rb") as source_file, captured.open("rb") as captured_file:
            if not _jsonl_identity_matches(os.fstat(source_file.fileno()), entry):
                return False
            remaining = entry.size
            while remaining:
                check_backup_cancelled()
                length = min(1024 * 1024, remaining)
                if source_file.read(length) != captured_file.read(length):
                    return False
                remaining -= length
            return _jsonl_identity_matches(os.fstat(source_file.fileno()), entry)
    except OSError:
        return False


def _run_git(
    project_dir: Path,
    args: list[str],
    *,
    text: bool = True,
    env: dict[str, str] | None = None,
    input_data: str | None = None,
) -> subprocess.CompletedProcess[Any]:
    check_backup_cancelled()
    git_environment = {
        **os.environ,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        **(env or {}),
    }
    if args and args[0] in {"bundle", "pack-objects", "index-pack", "unpack-objects", "fsck"}:
        if input_data is not None:
            raise ValueError("Bulk Git recovery commands do not accept buffered stdin")
        return run_bulk_process(
            ["git", "-C", str(project_dir), *args],
            env=git_environment,
            phase="git_recovery", attention_after=120, text=text,
        )
    return subprocess.run(
        ["git", "-C", str(project_dir), *args],
        capture_output=True,
        text=text,
        input=input_data,
        env=git_environment,
        timeout=120,
        check=False,
    )


def git_state(project_dir: Path) -> dict[str, Any] | None:
    """Return portable Git identity used to detect ref/index changes."""
    top = _run_git(project_dir, ["rev-parse", "--show-toplevel"])
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != project_dir.resolve():
        return None
    head = _run_git(project_dir, ["rev-parse", "--verify", "HEAD"])
    symbolic = _run_git(project_dir, ["symbolic-ref", "-q", "HEAD"])
    refs = _run_git(
        project_dir,
        ["for-each-ref", "--format=%(objectname) %(refname)"],
    )
    index_path_result = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", "index"])
    if head.returncode != 0 or refs.returncode != 0 or index_path_result.returncode != 0:
        raise RuntimeError("Unable to capture Git recovery state")
    index_path = Path(index_path_result.stdout.strip())
    object_format = _run_git(project_dir, ["rev-parse", "--show-object-format"])
    version = _run_git(project_dir, ["--version"])
    if object_format.returncode != 0 or version.returncode != 0:
        raise RuntimeError("Unable to capture Git recovery compatibility")
    stash = _run_git(project_dir, ["reflog", "show", "--format=%H%x00%gs", "refs/stash"])
    stash_entries = []
    if any(line.endswith(" refs/stash") for line in refs.stdout.splitlines()):
        if stash.returncode != 0:
            raise RuntimeError("Unable to capture Git stash recovery state")
        for line in stash.stdout.splitlines():
            object_id, separator, message = line.partition("\0")
            if not separator:
                raise RuntimeError("Invalid Git stash recovery state")
            stash_entries.append({"object_id": object_id, "message": message})
    shared_path = _shared_git_index_path(index_path, object_format.stdout.strip())
    shallow = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", "shallow"])
    if shallow.returncode != 0:
        raise RuntimeError("Unable to capture Git shallow state")
    shallow_path = Path(shallow.stdout.strip())
    return {
        "head": head.stdout.strip(),
        "head_ref": symbolic.stdout.strip() if symbolic.returncode == 0 else None,
        "refs": refs.stdout.splitlines(),
        "index_path": str(index_path),
        "index_checksum": _sha256(index_path) if index_path.is_file() else None,
        "object_format": object_format.stdout.strip(),
        "git_version": version.stdout.strip(),
        "recovery_format": GIT_RECOVERY_FORMAT,
        "stash_entries": stash_entries,
        "remote_config": _git_remote_config(project_dir),
        "shared_index_path": str(shared_path) if shared_path else None,
        "shared_index_checksum": _sha256(shared_path) if shared_path else None,
        "shallow_commits": sorted(shallow_path.read_text().splitlines()) if shallow_path.is_file() else [],
    }


def _shared_git_index_path(index_path: Path, object_format: str) -> Path | None:
    """Inspect a private copy because even Git index reads refresh split files."""
    candidates = list(index_path.parent.glob("sharedindex.*"))
    if not candidates or not index_path.is_file():
        return None
    with tempfile.TemporaryDirectory(prefix="backup-git-shared-index-") as temporary:
        repository = Path(temporary) / "index.git"
        initialized = _run_git(repository.parent, ["init", "--bare", f"--object-format={object_format}", str(repository)])
        if initialized.returncode != 0:
            raise RuntimeError("Unable to stage shared Git index inspection")
        shutil.copy2(index_path, repository / "index")
        for candidate in candidates:
            if not stat.S_ISREG(candidate.lstat().st_mode):
                raise RuntimeError("Shared Git index is not a regular file")
            shutil.copy2(candidate, repository / candidate.name)
        shared = _run_git(repository, ["rev-parse", "--path-format=absolute", "--shared-index-path"])
        if shared.returncode != 0:
            raise RuntimeError("Unable to capture shared Git index state")
        return index_path.parent / Path(shared.stdout.strip()).name if shared.stdout.strip() else None


def _git_remote_config(project_dir: Path) -> list[dict[str, str]]:
    """Keep remote/upstream identity, never executable config or URL secrets."""
    result = _run_git(project_dir, ["config", "--local", "--null", "--get-regexp", r"^(remote\..*\.(url|pushurl|fetch|mirror|tagopt)|branch\..*\.(remote|merge))$"])
    if result.returncode not in {0, 1}:
        raise RuntimeError("Unable to capture Git remote configuration")
    entries = []
    for entry in result.stdout.split("\0"):
        if not entry:
            continue
        key, separator, value = entry.partition("\n")
        if not separator:
            raise RuntimeError("Invalid Git remote configuration")
        if key.endswith((".url", ".pushurl")):
            parsed = urlsplit(value)
            if parsed.scheme and parsed.netloc:
                # Auth belongs to the owner's credential manager. Query strings
                # and fragments may also contain tokens and are not identity.
                host = parsed.netloc.rsplit("@", 1)[-1]
                if parsed.scheme not in {"http", "https"} and "@" in parsed.netloc:
                    host = parsed.netloc.rsplit("@", 1)[0].split(":", 1)[0] + "@" + host
                value = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        entries.append({"key": key, "value": value})
    return entries


def _open_metadata_directory(path: Path, *, create: bool = False, missing_ok: bool = False) -> int | None:
    """Walk every parent using directory descriptors, never following links."""
    absolute = Path(os.path.abspath(path))
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in absolute.parts[1:]:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if missing_ok:
                    return None
                raise
            os.close(descriptor)
            descriptor = child
        result, descriptor = descriptor, -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _metadata_file(path: Path, *, expected: SnapshotEntry | None = None, destination: Path | None = None) -> tuple[SnapshotEntry, str]:
    """Hash/copy exact regular bytes through non-linked parents and file handles."""
    parent = _open_metadata_directory(path.parent)
    assert parent is not None
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("ST recovery metadata must contain only regular files")
        entry = SnapshotEntry(kind="file", mode=stat.S_IMODE(metadata.st_mode), size=metadata.st_size, mtime_ns=metadata.st_mtime_ns, inode=metadata.st_ino)
        if expected is not None and entry != expected:
            raise RuntimeError("ST recovery metadata changed during capture")
        output = None
        if destination is not None:
            output_parent = _open_metadata_directory(destination.parent, create=True)
            assert output_parent is not None
            try:
                output_descriptor = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output_parent)
                output = os.fdopen(output_descriptor, "wb")
            finally:
                os.close(output_parent)
        try:
            digest = hashlib.sha256()
            while True:
                check_backup_cancelled()
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
            if not _regular_identity_matches(os.fstat(source.fileno()), entry):
                raise RuntimeError("ST recovery metadata changed during capture")
            if output is not None:
                os.fchmod(output.fileno(), entry.mode & 0o777)
        finally:
            if output is not None:
                output.close()
    return entry, f"sha256:{digest.hexdigest()}"


def _st_metadata_path_allowed(relative: str) -> bool:
    if not _safe_manifest_path(relative):
        return False
    parts = relative.split("/")
    if any(part.startswith(".") or part.endswith((".lock", ".tmp")) for part in parts):
        return False
    for root in ST_METADATA_ROOTS:
        if relative.startswith(root + "/"):
            suffix = relative[len(root) + 1:]
            if root in {"st/publication", "st-publication"}:
                return "/" not in suffix and suffix.endswith(".json")
            if root == "st/acceptance":
                return ("/" not in suffix and suffix.endswith(".json")) or suffix.startswith("isolated-observations/")
            # Native stage writers finalize proofs as <cache hash>-<stage id>
            # JSON and artifact blobs as their content hash. Interrupted
            # NamedTemporaryFile writes (tmp*) are not finalized evidence.
            return re.fullmatch(r"(?:[0-9a-f]{64}-[A-Za-z0-9][A-Za-z0-9_.-]*\.json|artifacts/[0-9a-f]{64})", suffix) is not None
    return False


def _st_metadata_directory_allowed(relative: str) -> bool:
    if not _safe_manifest_path(relative) or any(part.startswith(".") or part.endswith((".lock", ".tmp")) for part in relative.split("/")):
        return False
    return (
        any(root == relative or root.startswith(relative + "/") for root in ST_METADATA_ROOTS)
        or relative == "st/native-stages/artifacts"
        or relative == "st/acceptance/isolated-observations"
        or relative.startswith("st/acceptance/isolated-observations/")
    )


def _st_metadata_roots(project_dir: Path) -> dict[str, Path]:
    common = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    publication = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", "st-publication"])
    if common.returncode or publication.returncode:
        raise RuntimeError("Unable to locate ST recovery metadata")
    common_dir = Path(common.stdout.strip())
    return {**{root: common_dir / root for root in ST_METADATA_ROOTS if root != "st-publication"}, "st-publication": Path(publication.stdout.strip())}


def _inventory_st_metadata(roots: dict[str, Path], *, payload: bool = False, missing_ok: bool | None = None) -> dict[str, tuple[SnapshotEntry, str]]:
    inventory: dict[str, tuple[SnapshotEntry, str]] = {}

    def walk(directory: Path, relative: str, descriptor: int) -> None:
        with os.scandir(descriptor) as entries:
            names = sorted(entry.name for entry in entries)
        for name in names:
            check_backup_cancelled()
            rel = f"{relative}/{name}" if relative else name
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                if not _st_metadata_directory_allowed(rel):
                    if payload:
                        raise RuntimeError("ST recovery payload contains an unlisted metadata path")
                    continue
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    walk(directory / name, rel, child)
                finally:
                    os.close(child)
            elif _st_metadata_path_allowed(rel) or _st_metadata_directory_allowed(rel):
                if not stat.S_ISREG(metadata.st_mode) or not _st_metadata_path_allowed(rel):
                    raise RuntimeError("ST recovery metadata must contain only regular files")
                inventory[rel] = _metadata_file(directory / name)
            elif payload:
                raise RuntimeError("ST recovery payload contains an unlisted metadata path")

    try:
        for relative, root in roots.items():
            descriptor = _open_metadata_directory(root, missing_ok=not payload if missing_ok is None else missing_ok)
            if descriptor is None:
                continue
            try:
                walk(root, relative, descriptor)
            finally:
                os.close(descriptor)
    except OSError as exc:
        raise RuntimeError("ST recovery metadata path is unsafe or changed") from exc
    return inventory


def _copy_st_metadata(roots: dict[str, Path], destination: Path, inventory: dict[str, tuple[SnapshotEntry, str]]) -> dict[str, Any]:
    destination.mkdir(mode=0o700)
    files = []
    for relative, (entry, digest) in sorted(inventory.items()):
        root = next(root for root in roots if relative.startswith(root + "/"))
        source = roots[root] / relative[len(root) + 1:]
        _, copied_digest = _metadata_file(source, expected=entry, destination=destination / relative)
        if copied_digest != digest:
            raise RuntimeError("ST recovery metadata changed during capture")
        files.append({"path": relative, "sha256": digest, "size": entry.size, "mode": entry.mode & 0o777})
    return {"version": 1, "files": files}


def _validate_st_metadata_restore(project_dir: Path, recovery_dir: Path, manifest: dict[str, Any]) -> dict[str, tuple[SnapshotEntry, str]] | None:
    if "st_metadata" not in manifest:
        return None  # Older backups retain their existing recovery behavior.
    metadata = manifest["st_metadata"]
    if not isinstance(metadata, dict) or type(metadata.get("version")) is not int or metadata["version"] != 1 or not isinstance(metadata.get("files"), list):
        raise RuntimeError("Invalid ST recovery metadata manifest")
    expected: dict[str, dict[str, Any]] = {}
    for item in metadata["files"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256", "size", "mode"}
                or not isinstance(item.get("path"), str) or not _st_metadata_path_allowed(item["path"])
                or item["path"] in expected or type(item.get("mode")) is not int or not 0 <= item["mode"] <= 0o777
                or type(item.get("size")) is not int or item["size"] < 0
                or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["sha256"])):
            raise RuntimeError("Invalid ST recovery metadata entry")
        expected[item["path"]] = item
    # Native archives contain regular files, so a genuinely empty payload has
    # no directory member. A nonempty manifest must always have its payload.
    inventory = _inventory_st_metadata({"": recovery_dir / ST_METADATA_DIR_NAME}, payload=True, missing_ok=not expected)
    if inventory.keys() != expected.keys() or any(digest != expected[rel]["sha256"] or entry.size != expected[rel]["size"] or entry.mode != expected[rel]["mode"] for rel, (entry, digest) in inventory.items()):
        raise RuntimeError("ST recovery metadata checksum or file inventory mismatch")
    # This payload belongs only to an isolated reconstructed repository. Existing
    # metadata may be a foreign repository or pointer to another checkout.
    if (project_dir / ".git").exists() or (project_dir / ".git").is_symlink():
        raise RuntimeError("ST recovery refuses existing destination Git metadata")
    if any(os.environ.get(key) for key in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    )):
        raise RuntimeError("ST recovery refuses a redirected Git environment")
    descriptor = _open_metadata_directory(project_dir)
    assert descriptor is not None
    os.close(descriptor)
    return inventory


def _compact_git_plan(project_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Select unpublished ancestry and published edge trees, or retain all Git.

    Local remote-tracking refs are the capture's published baseline; capture
    never contacts a server. Missing baselines or unusual traversal semantics
    retain full history. The source repository is never made shallow.
    """
    full: dict[str, Any] = {"capture_mode": "full", "shallow_commits": state.get("shallow_commits", [])}
    if state.get("shallow_commits"):
        return {**full, "compact_fallback_reason": "source_already_shallow"}
    if any(" refs/replace/" in line for line in state["refs"]):
        return {**full, "compact_fallback_reason": "replacement_refs"}
    graft_path = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", "info/grafts"])
    if graft_path.returncode != 0 or Path(graft_path.stdout.strip()).exists():
        return {**full, "compact_fallback_reason": "uncertain_traversal"}
    remote_names = {item["key"][7:-4] for item in state.get("remote_config", []) if item["key"].startswith("remote.") and item["key"].endswith(".url")}
    published = []
    tips = [state["head"], *(line.split(" ", 1)[0] for line in state["refs"]), *(item["object_id"] for item in state.get("stash_entries", []))]
    for line in state["refs"]:
        object_id, ref_name = line.split(" ", 1)
        if ref_name.startswith("refs/remotes/"):
            if not any(ref_name.startswith(f"refs/remotes/{name}/") for name in remote_names):
                return {**full, "compact_fallback_reason": "unconfigured_remote_baseline"}
            published.append(object_id)
    if not published:
        return {**full, "compact_fallback_reason": "no_published_baseline"}
    peeled_commits = {}
    annotated_tags = []
    for tip in sorted(set(tips)):
        peeled = _run_git(project_dir, ["rev-parse", "--verify", f"{tip}^{{commit}}"])
        if peeled.returncode != 0:
            return {**full, "compact_fallback_reason": "non_commit_ref"}
        peeled_commits[tip] = peeled.stdout.strip()
        kind = _run_git(project_dir, ["cat-file", "-t", tip])
        if kind.returncode != 0:
            return {**full, "compact_fallback_reason": "uncertain_ref_type"}
        if kind.stdout.strip() == "tag":
            annotated_tags.append(tip)
    # Explicit stash reflog roots include older stashes which refs/stash alone
    # does not reach. All refs include unpublished work on other local branches.
    traversal = _run_git(project_dir, ["rev-list", "--boundary", *sorted(set(peeled_commits.values())), "--not", *sorted(set(published))])
    if traversal.returncode != 0:
        return {**full, "compact_fallback_reason": "published_traversal_failed"}
    unpublished = {line for line in traversal.stdout.splitlines() if not line.startswith("-")}
    boundaries = {line[1:] for line in traversal.stdout.splitlines() if line.startswith("-")}
    # A remote-tracking branch proves commit publication, not publication of
    # annotation messages/signatures. Preserve annotated tag objects regardless
    # of whether their target commits are already published.
    required_tips = [state["head"], *annotated_tags, *(entry["object_id"] for entry in state.get("stash_entries", []))]
    boundaries.update(peeled_commits[tip] for tip in required_tips if peeled_commits[tip] not in unpublished)
    # Published refs unrelated to current/unpublished work would reintroduce
    # entire historical trees. Retain their names only if their objects already
    # belong to this recovery graph; remote identity remains in configuration.
    retained = [line for line in state["refs"] if peeled_commits[line.split(" ", 1)[0]] in unpublished | boundaries]
    return {
        "capture_mode": "compact", "shallow_commits": sorted(boundaries),
        "unpublished_commit_count": len(unpublished), "refs": retained,
        "omitted_published_ref_count": len(state["refs"]) - len(retained),
    }


def create_git_recovery_payload(
    project_dir: Path,
    snapshot_dir: Path,
    state: dict[str, Any] | None,
    *,
    git_bundle_reuse: dict[str, Any] | None = None,
    git_history_mode: str = "full",
) -> dict[str, Any]:
    """Create a bundle and copy the exact Git index into the staged snapshot."""
    if git_history_mode not in {"full", "compact"}:
        raise ValueError("Unsupported Git history capture mode")
    recovery_dir = snapshot_dir / RECOVERY_DIR_NAME
    recovery_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "version": 1,
        "git": None,
        "jj_present": (project_dir / ".jj").exists(),
    }
    if state is not None:
        plan = _compact_git_plan(project_dir, state) if git_history_mode == "compact" else {"capture_mode": "full", "shallow_commits": state.get("shallow_commits", [])}
        bundle_state = {**state, **plan, "recovery_format": 2 if plan["capture_mode"] == "compact" else GIT_RECOVERY_FORMAT}
        bundle = recovery_dir / GIT_BUNDLE_NAME
        index_path = Path(str(state["index_path"]))
        saved_index = recovery_dir / GIT_INDEX_NAME
        if index_path.is_file():
            shutil.copy2(index_path, saved_index)
        if saved_index.is_file() and _sha256(saved_index) != state["index_checksum"]:
            raise RuntimeError("Backup source changed during Git index capture")
        if state.get("shared_index_path"):
            shared_index = recovery_dir / GIT_SHARED_INDEX_NAME
            shutil.copy2(Path(state["shared_index_path"]), shared_index)
            if _sha256(shared_index) != state["shared_index_checksum"]:
                raise RuntimeError("Backup source changed during shared Git index capture")
        if not _reuse_git_bundle(project_dir, bundle, bundle_state, git_bundle_reuse):
            _create_git_bundle(
                project_dir, bundle, bundle_state,
                saved_index if saved_index.is_file() else None,
            )
        verified = _run_git(project_dir, ["bundle", "verify", str(bundle)])
        if verified.returncode != 0:
            raise RuntimeError(f"Git bundle verification failed: {verified.stderr.strip()}")
        manifest["git"] = {
            "head": state["head"],
            "head_ref": state["head_ref"],
            "refs": state["refs"],
            "index_checksum": state["index_checksum"],
            "bundle_checksum": _sha256(bundle),
            "object_format": state.get("object_format", "sha1"),
            "git_version": state.get("git_version"),
            "recovery_format": bundle_state["recovery_format"],
            **plan,
            "stash_entries": state.get("stash_entries", []),
            "remote_config": state.get("remote_config", []),
            "shared_index_name": Path(state["shared_index_path"]).name if state.get("shared_index_path") else None,
            "shared_index_checksum": state.get("shared_index_checksum"),
        }
    (recovery_dir / RECOVERY_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def _reuse_git_bundle(
    project_dir: Path, destination: Path, state: dict[str, Any],
    reuse: dict[str, Any] | None,
) -> bool:
    """Accept only a compatible self-contained bundle from private staging."""
    if not reuse or not isinstance(reuse.get("git"), dict):
        return False
    previous = reuse["git"]
    compatibility = ("head", "head_ref", "refs", "index_checksum", "object_format", "git_version", "recovery_format")
    if any(previous.get(key) != state.get(key) for key in compatibility):
        return False
    optional_defaults = {"capture_mode": "full", "shallow_commits": [], "stash_entries": [], "shared_index_checksum": None}
    if any(previous.get(key, default) != state.get(key, default) for key, default in optional_defaults.items()):
        return False
    try:
        source = Path(reuse["bundle_path"])
        if not stat.S_ISREG(source.lstat().st_mode) or _sha256(source) != previous.get("bundle_checksum"):
            return False
        shutil.copy2(source, destination, follow_symlinks=False)
        if _sha256(destination) != previous.get("bundle_checksum"):
            destination.unlink()
            return False
        # Verification in an empty repository rejects prerequisite/incremental
        # bundles even when the live repository contains their prerequisite.
        with tempfile.TemporaryDirectory(prefix="backup-git-reuse-") as temporary:
            empty_repo = Path(temporary) / "empty.git"
            initialized = _run_git(empty_repo.parent, ["init", "--bare", f"--object-format={state['object_format']}", str(empty_repo)])
            if initialized.returncode != 0:
                destination.unlink()
                return False
            verified = _run_git(empty_repo, ["bundle", "verify", str(destination)])
        if verified.returncode != 0:
            destination.unlink()
            return False
        return True
    except BackupCancelled:
        raise
    except (OSError, KeyError, TypeError, ValueError):
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        return False


def _create_index_commit(
    bundle_repo: Path,
    saved_index: Path | None,
) -> str | None:
    """Retain exact index objects, writing synthetic objects only in staging."""
    index_commit_id: str | None = None
    if saved_index is not None:
        with tempfile.TemporaryDirectory(prefix="backup-git-index-") as temporary:
            working_index = Path(temporary) / "index"
            shutil.copy2(saved_index, working_index)
            entries = _run_git(
                bundle_repo,
                ["ls-files", "--stage", "-z"],
                env={"GIT_INDEX_FILE": str(working_index)},
            )
            if entries.returncode != 0:
                raise RuntimeError("Git index object inventory failed")
            # The original index bytes retain paths, stages and intent-to-add
            # flags. A flat synthetic tree only keeps referenced objects alive;
            # write-tree cannot encode unmerged or file/directory-conflict states.
            objects: dict[str, str] = {}
            for entry in entries.stdout.split("\0"):
                if not entry:
                    continue
                mode, object_id, _stage = entry.split("\t", 1)[0].split()
                if mode == "160000":
                    continue  # Submodule commits belong to the submodule repo.
                object_type = "tree" if mode == "040000" else "blob"
                objects[object_id] = f"{mode} {object_type} {object_id}\t{object_id}\0"
            index_tree = _run_git(
                bundle_repo,
                ["mktree", "--missing", "-z"],
                input_data="".join(objects[key] for key in sorted(objects)),
            )
            if index_tree.returncode != 0:
                raise RuntimeError(f"Git index tree capture failed: {index_tree.stderr.strip()}")
            index_commit = _run_git(
                bundle_repo,
                [
                    "-c",
                    "user.name=SummitFlow Backup",
                    "-c",
                    "user.email=backup@localhost.invalid",
                    "commit-tree",
                    index_tree.stdout.strip(),
                    "-m",
                    "SummitFlow staged index recovery",
                ],
                env={
                    "GIT_AUTHOR_NAME": "SummitFlow Backup", "GIT_COMMITTER_NAME": "SummitFlow Backup",
                    "GIT_AUTHOR_EMAIL": "backup@localhost.invalid", "GIT_COMMITTER_EMAIL": "backup@localhost.invalid",
                    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
                },
            )
        if index_commit.returncode != 0:
            raise RuntimeError(f"Git index commit capture failed: {index_commit.stderr.strip()}")
        index_commit_id = index_commit.stdout.strip()
    return index_commit_id


def _create_git_bundle(
    project_dir: Path,
    bundle: Path,
    state: dict[str, Any],
    saved_index: Path | None,
) -> None:
    """Bundle original refs and index objects without writing original Git."""
    object_dir_result = _run_git(
        project_dir,
        ["rev-parse", "--path-format=absolute", "--git-path", "objects"],
    )
    if object_dir_result.returncode != 0:
        raise RuntimeError("Unable to locate Git object directory")

    with tempfile.TemporaryDirectory(prefix="backup-git-bundle-") as temporary:
        bundle_repo = Path(temporary) / "recovery.git"
        initialized = _run_git(bundle_repo.parent, ["init", "--bare", f"--object-format={state.get('object_format', 'sha1')}", str(bundle_repo)])
        if initialized.returncode != 0:
            raise RuntimeError(f"Git bundle staging failed: {initialized.stderr.strip()}")
        if state.get("shared_index_path"):
            shared_source = Path(state["shared_index_path"])
            shutil.copy2(shared_source, bundle_repo / shared_source.name)
        # Writing an object already present in an alternate can refresh the
        # original loose object's mtime. Create synthetic objects before adding
        # read-only access to the source. Their flat tree permits missing blobs
        # until the original object directory becomes available for packing.
        index_commit_id = _create_index_commit(bundle_repo, saved_index)
        alternates = bundle_repo / "objects" / "info" / "alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(object_dir_result.stdout.strip() + "\n", encoding="utf-8")
        shallow_commits = state.get("shallow_commits", [])
        if shallow_commits:
            (bundle_repo / "shallow").write_text("\n".join(shallow_commits) + "\n", encoding="ascii")

        recovery_refs = [
            *state.get("refs", []),
            f"{state['head']} refs/summitflow-recovery/head",
            *(f"{entry['object_id']} refs/summitflow-recovery/stash/{position}" for position, entry in enumerate(state.get("stash_entries", []))),
        ]
        if index_commit_id:
            recovery_refs.append(
                f"{index_commit_id} refs/summitflow-recovery/index"
            )
        for ref_line in recovery_refs:
            object_id, separator, ref_name = str(ref_line).partition(" ")
            if not separator or not ref_name.startswith("refs/"):
                raise RuntimeError("Invalid ref while creating Git recovery bundle")
            updated = _run_git(bundle_repo, ["update-ref", ref_name, object_id])
            if updated.returncode != 0:
                raise RuntimeError(f"Git bundle ref staging failed: {ref_name}")

        created = _run_git(bundle_repo, ["bundle", "create", str(bundle), "--all"])
        if created.returncode != 0:
            raise RuntimeError(f"Git bundle creation failed: {created.stderr.strip()}")


def build_consistent_snapshot(
    project_dir: Path,
    staging: Path,
    excludes: tuple[str, ...],
    should_exclude: Any,
    sensitive_paths: tuple[Path, ...] = (),
    *,
    source_roots: dict[str, Path] | None = None,
    git_bundle_reuse: dict[str, Any] | None = None,
    capture_git: bool = True,
    git_history_mode: str = "full",
) -> tuple[Path, dict[str, Any]]:
    """Stage a tree and fail closed if source files or Git refs changed."""
    root_metadata = project_dir.lstat()
    if not (stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISREG(root_metadata.st_mode)):
        raise RuntimeError("Backup source must be a directory or explicit regular file")
    file_source = stat.S_ISREG(root_metadata.st_mode)
    key_excludes: list[str] = []
    candidates = [*sensitive_paths, backup_key_directory()]
    for raw_path in candidates:
        candidate = raw_path.expanduser().resolve(strict=False)
        if project_dir.resolve().is_relative_to(candidate):
            raise RuntimeError("Backup source is an excluded sensitive path")
        try:
            key_excludes.append(candidate.relative_to(project_dir.resolve()).as_posix())
        except ValueError:
            continue
    effective_excludes = (*excludes, RECOVERY_DIR_NAME, *key_excludes)
    before = inventory_project_tree(project_dir, effective_excludes, should_exclude, source_roots=source_roots, sensitive_paths=sensitive_paths)
    git_before = None if file_source or not capture_git else git_state(project_dir)
    st_roots = _st_metadata_roots(project_dir) if git_before is not None else {}
    st_before = _inventory_st_metadata(st_roots)
    if not before and git_before is None:
        raise RuntimeError("Backup source contains no regular files")
    snapshot_dir = staging / "project-snapshot"
    copy_inventory_snapshot(project_dir, snapshot_dir, before)
    recovery = create_git_recovery_payload(project_dir, snapshot_dir, git_before, git_bundle_reuse=git_bundle_reuse, git_history_mode=git_history_mode)
    if git_before is not None:
        recovery["st_metadata"] = _copy_st_metadata(st_roots, snapshot_dir / RECOVERY_DIR_NAME / ST_METADATA_DIR_NAME, st_before)
    after = inventory_project_tree(project_dir, effective_excludes, should_exclude, source_roots=source_roots, sensitive_paths=sensitive_paths)
    git_after = None if file_source or not capture_git else git_state(project_dir)
    st_roots_after = _st_metadata_roots(project_dir) if git_after is not None else {}
    st_after = _inventory_st_metadata(st_roots_after)
    changed = sorted(
        relative_path
        for relative_path in set(before) | set(after)
        if not _snapshot_entry_is_stable(
            project_dir,
            snapshot_dir,
            relative_path,
            before.get(relative_path),
            after.get(relative_path),
        )
    )
    if changed or git_before != git_after or st_roots != st_roots_after or st_before != st_after:
        raise RuntimeError(
            "Backup source changed during capture"
            + (f": {', '.join(changed[:5])}" if changed else "")
        )
    recovery.update(
        {
            "snapshot_files": sum(entry.kind == "file" for entry in before.values()),
            "snapshot_symlinks": sum(entry.kind == "symlink" for entry in before.values()),
            "source_kind": "file" if file_source else "directory",
            "file_name": project_dir.name if file_source else None,
            "mapped_links_version": 1,
            "mapped_links": [
                {"path": rel, "target_source": entry.target_source, "target_relative_path": entry.target_relative_path}
                for rel, entry in sorted(before.items()) if entry.kind == "mapped_link"
            ],
            "consistent": True,
            "point_in_time_json_files": sorted(rel for rel, entry in before.items() if entry.point_in_time_json),
        }
    )
    manifest_path = snapshot_dir / RECOVERY_DIR_NAME / RECOVERY_MANIFEST_NAME
    manifest_path.write_text(json.dumps(recovery, indent=2, sort_keys=True) + "\n")
    return snapshot_dir, recovery


def _snapshot_entry_is_stable(
    project_dir: Path,
    snapshot_dir: Path,
    relative_path: str,
    before: SnapshotEntry | None,
    after: SnapshotEntry | None,
) -> bool:
    if before is None or after is None:
        return False
    if before.point_in_time_json:
        # The copy operation already checked the opened inode before/after its
        # read and validated the complete JSON. Later desktop updates do not
        # invalidate that point-in-time document. Type/mode changes still fail.
        return after.point_in_time_json and after.kind == before.kind and after.mode == before.mode
    if not before.append_only_jsonl:
        if before != after:
            return False
        if before.kind != "file" or before.sqlite_database:
            return True
        source = project_dir if project_dir.is_file() else project_dir / Path(*PurePosixPath(relative_path).parts)
        captured = snapshot_dir / Path(*PurePosixPath(relative_path).parts)
        try:
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source_file, captured.open("rb") as captured_file:
                if not _regular_identity_matches(os.fstat(source_file.fileno()), before):
                    return False
                while True:
                    check_backup_cancelled()
                    chunk = source_file.read(1024 * 1024)
                    if chunk != captured_file.read(len(chunk) if chunk else 1):
                        return False
                    if not chunk:
                        break
                return _regular_identity_matches(os.fstat(source_file.fileno()), before)
        except OSError:
            return False
    if (
        not after.append_only_jsonl
        or after.kind != before.kind
        or after.mode != before.mode
        or after.inode != before.inode
        or after.size < before.size
    ):
        return False
    source = project_dir if project_dir.is_file() else project_dir / Path(*PurePosixPath(relative_path).parts)
    captured = snapshot_dir / Path(*PurePosixPath(relative_path).parts)
    return _jsonl_prefix_matches(source, captured, before)


def restore_mapped_links(
    project_dir: Path,
    *,
    destination_roots: dict[str, Path],
    isolated_root: Path,
) -> dict[str, Any]:
    """Restore registered link identities after all target sources are restored.

    Caller supplies destination roots explicitly. No host source paths from the
    capture manifest are used, and every link and resolved target stays inside
    the caller's isolated recovery root. Legacy manifests need no mapping.
    """
    manifest_path = project_dir / RECOVERY_DIR_NAME / RECOVERY_MANIFEST_NAME
    if not manifest_path.is_file():
        return {"mapped_links_restored": 0}
    manifest = json.loads(manifest_path.read_text())
    mappings = manifest.get("mapped_links", [])
    if not mappings:
        return {"mapped_links_restored": 0}
    if manifest.get("mapped_links_version") != 1 or not isinstance(mappings, list):
        raise RuntimeError("Unsupported mapped link recovery format")
    isolated = isolated_root.resolve(strict=True)
    project = project_dir.resolve(strict=True)
    if not project.is_relative_to(isolated):
        raise RuntimeError("Mapped link source is outside isolated recovery root")
    planned: list[tuple[Path, Path]] = []
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise RuntimeError("Invalid mapped link recovery entry")
        path = mapping.get("path")
        relative_target = mapping.get("target_relative_path")
        source_name = mapping.get("target_source")
        if (
            not _safe_manifest_path(path)
            or not _safe_manifest_path(relative_target, allow_root=True)
            or not isinstance(source_name, str)
            or source_name not in destination_roots
            or path in seen
        ):
            raise RuntimeError("Invalid or unregistered mapped link recovery path")
        if any(PurePosixPath(path).is_relative_to(PurePosixPath(existing)) or PurePosixPath(existing).is_relative_to(PurePosixPath(path)) for existing in seen):
            raise RuntimeError("Mapped link recovery paths overlap")
        seen.add(path)
        link = project / path
        target_root = destination_roots[source_name].resolve(strict=True)
        target_candidate = target_root / relative_target
        target = target_candidate.resolve(strict=False)
        if (
            not target_root.is_relative_to(isolated)
            or not target.is_relative_to(target_root)
            or not target.is_relative_to(isolated)
            or not link.parent.resolve(strict=False).is_relative_to(project)
            or link.exists() or link.is_symlink()
        ):
            raise RuntimeError("Mapped link recovery would escape or overwrite isolated content")
        if not target_candidate.exists():
            # A captured link may already have been dangling at source. Keep
            # that dependency visible without failing the usable siblings.
            pending.append(mapping)
            continue
        planned.append((link, target))
    for link, target in planned:
        check_backup_cancelled()
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(os.path.relpath(target, link.parent))
    return {"mapped_links_restored": len(planned), "mapped_links_pending": pending}


def _safe_manifest_path(value: Any, *, allow_root: bool = False) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    if allow_root and value == ".":
        return True
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in value.split("/"))


def restore_git_recovery(project_dir: Path) -> dict[str, Any]:
    """Rebuild Git metadata in an isolated extracted project directory."""
    recovery_dir = project_dir / RECOVERY_DIR_NAME
    manifest_path = recovery_dir / RECOVERY_MANIFEST_NAME
    if not manifest_path.is_file():
        return {"git_restored": False, "reason": "recovery manifest missing"}
    manifest = json.loads(manifest_path.read_text())
    git_manifest = manifest.get("git")
    if not isinstance(git_manifest, dict):
        return {"git_restored": False, "reason": "archive has no Git repository"}
    st_inventory = _validate_st_metadata_restore(project_dir, recovery_dir, manifest)
    if git_manifest.get("recovery_format", 1) not in {1, 2}:
        raise RuntimeError("Unsupported Git recovery format")
    object_format = git_manifest.get("object_format", "sha1")
    if object_format not in {"sha1", "sha256"}:
        raise RuntimeError("Unsupported Git recovery object format")
    object_length = 40 if object_format == "sha1" else 64
    object_pattern = re.compile(rf"[0-9a-f]{{{object_length}}}")
    shallow_commits = git_manifest.get("shallow_commits", [])
    if not isinstance(shallow_commits, list) or any(not isinstance(commit, str) or not object_pattern.fullmatch(commit) for commit in shallow_commits):
        raise RuntimeError("Invalid Git shallow recovery boundaries")
    remote_config = git_manifest.get("remote_config", [])
    config_pattern = re.compile(r"(?:remote\..+\.(?:url|pushurl|fetch|mirror|tagopt)|branch\..+\.(?:remote|merge))")
    if not isinstance(remote_config, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not config_pattern.fullmatch(entry["key"]) or not isinstance(entry.get("value"), str) or "\0" in entry["value"] for entry in remote_config):
        raise RuntimeError("Invalid Git remote recovery configuration")
    stash_entries = git_manifest.get("stash_entries", [])
    if not isinstance(stash_entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("object_id"), str) or not object_pattern.fullmatch(entry["object_id"]) or not isinstance(entry.get("message"), str) or "\0" in entry["message"] for entry in stash_entries):
        raise RuntimeError("Invalid Git stash recovery entries")
    shared_index_name = git_manifest.get("shared_index_name")
    if shared_index_name is not None and (not isinstance(shared_index_name, str) or not re.fullmatch(r"sharedindex\.[0-9a-f]{40}|sharedindex\.[0-9a-f]{64}", shared_index_name)):
        raise RuntimeError("Invalid shared Git index recovery name")
    bundle = recovery_dir / GIT_BUNDLE_NAME
    if _sha256(bundle) != git_manifest.get("bundle_checksum"):
        raise RuntimeError("Git recovery bundle checksum mismatch")
    saved_index = recovery_dir / GIT_INDEX_NAME
    if git_manifest.get("index_checksum") is not None and (not saved_index.is_file() or _sha256(saved_index) != git_manifest["index_checksum"]):
        raise RuntimeError("Git recovery index checksum mismatch")
    initialized = _run_git(project_dir, ["init", f"--object-format={git_manifest.get('object_format', 'sha1')}"])
    if initialized.returncode != 0:
        raise RuntimeError(f"Git initialization failed: {initialized.stderr.strip()}")
    if shallow_commits:
        shallow_path_result = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", "shallow"])
        if shallow_path_result.returncode != 0:
            raise RuntimeError("Unable to locate Git shallow recovery path")
        Path(shallow_path_result.stdout.strip()).write_text("\n".join(shallow_commits) + "\n", encoding="ascii")
    unbundled = _run_git(project_dir, ["bundle", "unbundle", str(bundle)])
    if unbundled.returncode != 0:
        raise RuntimeError(f"Git bundle restore failed: {unbundled.stderr.strip()}")
    for commit in shallow_commits:
        exists = _run_git(project_dir, ["cat-file", "-t", commit])
        if exists.returncode != 0 or exists.stdout.strip() != "commit":
            raise RuntimeError("Missing Git shallow recovery boundary")
    for ref_line in git_manifest.get("refs", []):
        object_id, separator, ref_name = str(ref_line).partition(" ")
        if not separator or not ref_name.startswith("refs/"):
            raise RuntimeError("Invalid ref in Git recovery manifest")
        checked = _run_git(project_dir, ["check-ref-format", ref_name])
        if checked.returncode != 0:
            raise RuntimeError("Invalid ref in Git recovery manifest")
        if ref_name == "refs/stash" and stash_entries:
            continue
        updated = _run_git(project_dir, ["update-ref", ref_name, object_id])
        if updated.returncode != 0:
            raise RuntimeError(f"Unable to restore Git ref: {ref_name}")
    for entry in reversed(cast(list[dict[str, str]], stash_entries)):
        updated = _run_git(project_dir, ["update-ref", "--create-reflog", "-m", entry["message"], "refs/stash", entry["object_id"]])
        if updated.returncode != 0:
            raise RuntimeError("Unable to restore Git stash reflog")
    for entry in cast(list[dict[str, str]], remote_config):
        configured = _run_git(project_dir, ["config", "--local", "--add", entry["key"], entry["value"]])
        if configured.returncode != 0:
            raise RuntimeError("Unable to restore Git remote configuration")
    head_ref = git_manifest.get("head_ref")
    if isinstance(head_ref, str) and head_ref:
        result = _run_git(project_dir, ["symbolic-ref", "HEAD", head_ref])
    else:
        result = _run_git(project_dir, ["update-ref", "--no-deref", "HEAD", str(git_manifest["head"])])
    if result.returncode != 0:
        raise RuntimeError("Unable to restore Git HEAD")
    if shared_index_name:
        saved_shared = recovery_dir / GIT_SHARED_INDEX_NAME
        if _sha256(saved_shared) != git_manifest.get("shared_index_checksum"):
            raise RuntimeError("Shared Git recovery index checksum mismatch")
        shared_path_result = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", shared_index_name])
        if shared_path_result.returncode != 0:
            raise RuntimeError("Unable to locate shared Git recovery index path")
        shutil.copy2(saved_shared, Path(shared_path_result.stdout.strip()))
    if saved_index.is_file():
        index_result = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", "index"])
        index_path = Path(index_result.stdout.strip())
        index_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(saved_index, index_path)
        if _sha256(index_path) != git_manifest.get("index_checksum"):
            raise RuntimeError("Git recovery index checksum mismatch")
    if st_inventory is not None:
        for relative, (entry, digest) in sorted(st_inventory.items()):
            _, restored_digest = _metadata_file(
                recovery_dir / ST_METADATA_DIR_NAME / relative,
                expected=entry,
                destination=project_dir / ".git" / relative,
            )
            if restored_digest != digest:
                raise RuntimeError("ST recovery metadata changed during restore")
    return {
        "git_restored": True,
        "head": git_manifest["head"],
        "head_ref": head_ref,
        "refs_restored": len(git_manifest.get("refs", [])),
        "jj_present": bool(manifest.get("jj_present")),
        "st_metadata_files_restored": len(st_inventory) if st_inventory is not None else 0,
    }
