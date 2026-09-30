"""Portable, consistent recovery payloads for native project backups."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..services.backup_keys import backup_key_directory
from .backup_activity import BackupCancelled, backup_phase, check_backup_cancelled, run_bulk_process

RECOVERY_DIR_NAME = ".summitflow-recovery"
RECOVERY_MANIFEST_NAME = "manifest.json"
GIT_BUNDLE_NAME = "git.bundle"
GIT_INDEX_NAME = "git-index"
GIT_RECOVERY_FORMAT = 1
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
    if args and args[0] in {"bundle", "pack-objects", "index-pack", "unpack-objects", "fsck"}:
        if input_data is not None:
            raise ValueError("Bulk Git recovery commands do not accept buffered stdin")
        return run_bulk_process(
            ["git", "-C", str(project_dir), *args],
            env={**os.environ, **env} if env else None,
            phase="git_recovery", attention_after=120, text=text,
        )
    return subprocess.run(
        ["git", "-C", str(project_dir), *args],
        capture_output=True,
        text=text,
        input=input_data,
        env={**os.environ, **env} if env else None,
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
    return {
        "head": head.stdout.strip(),
        "head_ref": symbolic.stdout.strip() if symbolic.returncode == 0 else None,
        "refs": refs.stdout.splitlines(),
        "index_path": str(index_path),
        "index_checksum": _sha256(index_path) if index_path.is_file() else None,
        "object_format": object_format.stdout.strip(),
        "git_version": version.stdout.strip(),
        "recovery_format": GIT_RECOVERY_FORMAT,
    }


def create_git_recovery_payload(
    project_dir: Path,
    snapshot_dir: Path,
    state: dict[str, Any] | None,
    *,
    git_bundle_reuse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a bundle and copy the exact Git index into the staged snapshot."""
    recovery_dir = snapshot_dir / RECOVERY_DIR_NAME
    recovery_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "version": 1,
        "git": None,
        "jj_present": (project_dir / ".jj").exists(),
    }
    if state is not None:
        bundle = recovery_dir / GIT_BUNDLE_NAME
        index_path = Path(str(state["index_path"]))
        saved_index = recovery_dir / GIT_INDEX_NAME
        if index_path.is_file():
            shutil.copy2(index_path, saved_index)
        if saved_index.is_file() and _sha256(saved_index) != state["index_checksum"]:
            raise RuntimeError("Backup source changed during Git index capture")
        if not _reuse_git_bundle(project_dir, bundle, state, git_bundle_reuse):
            _create_git_bundle(
                project_dir, bundle, state,
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
            "recovery_format": GIT_RECOVERY_FORMAT,
        }
    (recovery_dir / RECOVERY_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def _reuse_git_bundle(
    project_dir: Path, destination: Path, state: dict[str, Any],
    reuse: dict[str, Any] | None,
) -> bool:
    """Accept only a compatible full bundle from caller-owned private staging."""
    if not reuse or not isinstance(reuse.get("git"), dict):
        return False
    previous = reuse["git"]
    compatibility = ("head", "head_ref", "refs", "index_checksum", "object_format", "git_version", "recovery_format")
    if any(previous.get(key) != state.get(key) for key in compatibility):
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


def _create_git_bundle(
    project_dir: Path,
    bundle: Path,
    state: dict[str, Any],
    saved_index: Path | None,
) -> None:
    """Bundle refs and index objects, including non-commit-ready indexes."""
    index_commit_id: str | None = None
    if saved_index is not None:
        with tempfile.TemporaryDirectory(prefix="backup-git-index-") as temporary:
            working_index = Path(temporary) / "index"
            shutil.copy2(saved_index, working_index)
            entries = _run_git(
                project_dir,
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
                project_dir,
                ["mktree", "-z"],
                input_data="".join(objects[key] for key in sorted(objects)),
            )
            if index_tree.returncode != 0:
                raise RuntimeError(f"Git index tree capture failed: {index_tree.stderr.strip()}")
            index_commit = _run_git(
                project_dir,
                [
                    "-c",
                    "user.name=SummitFlow Backup",
                    "-c",
                    "user.email=backup@localhost.invalid",
                    "commit-tree",
                    index_tree.stdout.strip(),
                    "-p",
                    str(state["head"]),
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
        alternates = bundle_repo / "objects" / "info" / "alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(object_dir_result.stdout.strip() + "\n", encoding="utf-8")

        recovery_refs = [
            *state.get("refs", []),
            f"{state['head']} refs/summitflow-recovery/head",
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
    if not before and git_before is None:
        raise RuntimeError("Backup source contains no regular files")
    snapshot_dir = staging / "project-snapshot"
    copy_inventory_snapshot(project_dir, snapshot_dir, before)
    recovery = create_git_recovery_payload(project_dir, snapshot_dir, git_before, git_bundle_reuse=git_bundle_reuse)
    after = inventory_project_tree(project_dir, effective_excludes, should_exclude, source_roots=source_roots, sensitive_paths=sensitive_paths)
    git_after = None if file_source or not capture_git else git_state(project_dir)
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
    if changed or git_before != git_after:
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
    bundle = recovery_dir / GIT_BUNDLE_NAME
    if _sha256(bundle) != git_manifest.get("bundle_checksum"):
        raise RuntimeError("Git recovery bundle checksum mismatch")
    initialized = _run_git(project_dir, ["init", f"--object-format={git_manifest.get('object_format', 'sha1')}"])
    if initialized.returncode != 0:
        raise RuntimeError(f"Git initialization failed: {initialized.stderr.strip()}")
    unbundled = _run_git(project_dir, ["bundle", "unbundle", str(bundle)])
    if unbundled.returncode != 0:
        raise RuntimeError(f"Git bundle restore failed: {unbundled.stderr.strip()}")
    for ref_line in git_manifest.get("refs", []):
        object_id, separator, ref_name = str(ref_line).partition(" ")
        if not separator or not ref_name.startswith("refs/"):
            raise RuntimeError("Invalid ref in Git recovery manifest")
        checked = _run_git(project_dir, ["check-ref-format", ref_name])
        if checked.returncode != 0:
            raise RuntimeError("Invalid ref in Git recovery manifest")
        updated = _run_git(project_dir, ["update-ref", ref_name, object_id])
        if updated.returncode != 0:
            raise RuntimeError(f"Unable to restore Git ref: {ref_name}")
    head_ref = git_manifest.get("head_ref")
    if isinstance(head_ref, str) and head_ref:
        result = _run_git(project_dir, ["symbolic-ref", "HEAD", head_ref])
    else:
        result = _run_git(project_dir, ["update-ref", "--no-deref", "HEAD", str(git_manifest["head"])])
    if result.returncode != 0:
        raise RuntimeError("Unable to restore Git HEAD")
    saved_index = recovery_dir / GIT_INDEX_NAME
    if saved_index.is_file():
        index_result = _run_git(project_dir, ["rev-parse", "--path-format=absolute", "--git-path", "index"])
        index_path = Path(index_result.stdout.strip())
        index_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(saved_index, index_path)
        if _sha256(index_path) != git_manifest.get("index_checksum"):
            raise RuntimeError("Git recovery index checksum mismatch")
    return {
        "git_restored": True,
        "head": git_manifest["head"],
        "head_ref": head_ref,
        "refs_restored": len(git_manifest.get("refs", [])),
        "jj_present": bool(manifest.get("jj_present")),
    }
