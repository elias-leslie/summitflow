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
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ..services.backup_keys import backup_key_directory

RECOVERY_DIR_NAME = ".summitflow-recovery"
RECOVERY_MANIFEST_NAME = "manifest.json"
GIT_BUNDLE_NAME = "git.bundle"
GIT_INDEX_NAME = "git-index"


@dataclass(frozen=True)
class SnapshotEntry:
    """Source metadata used to detect concurrent tree changes."""

    kind: str
    mode: int
    size: int
    mtime_ns: int
    inode: int
    link_target: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
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
) -> dict[str, SnapshotEntry]:
    """Inventory included regular files and safe in-tree relative symlinks."""
    inventory: dict[str, SnapshotEntry] = {}

    def walk_error(error: OSError) -> None:
        raise error

    for root, dirs, files in os.walk(project_dir, followlinks=False, onerror=walk_error):
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
                _record_symlink(inventory, path, rel, project_dir)
            elif stat.S_ISDIR(mode):
                retained_dirs.append(dirname)
        dirs[:] = retained_dirs

        for filename in files:
            path = root_path / filename
            rel = (Path(rel_root) / filename).as_posix()
            if should_exclude(rel, excludes):
                continue
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                raise RuntimeError(f"Backup source changed during inventory: {rel}") from None
            if stat.S_ISLNK(metadata.st_mode):
                _record_symlink(inventory, path, rel, project_dir)
            elif stat.S_ISREG(metadata.st_mode):
                inventory[rel] = SnapshotEntry(
                    kind="file",
                    mode=stat.S_IMODE(metadata.st_mode),
                    size=metadata.st_size,
                    mtime_ns=metadata.st_mtime_ns,
                    inode=metadata.st_ino,
                )
    return inventory


def _record_symlink(
    inventory: dict[str, SnapshotEntry],
    path: Path,
    rel: str,
    project_dir: Path,
) -> None:
    metadata = path.lstat()
    target = os.readlink(path)
    if not _safe_relative_symlink(path, project_dir, target):
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
        with path.open("rb") as source:
            return source.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_db, sqlite3.connect(destination) as destination_db:
        source_db.backup(destination_db)
    shutil.copystat(source, destination, follow_symlinks=False)


def copy_inventory_snapshot(
    project_dir: Path,
    destination: Path,
    inventory: dict[str, SnapshotEntry],
) -> None:
    """Copy exactly one inventory without following links or special files."""
    destination.mkdir(parents=True, exist_ok=True)
    for rel, entry in sorted(inventory.items()):
        source = project_dir / Path(*PurePosixPath(rel).parts)
        target = destination / Path(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.kind == "symlink":
            target.symlink_to(entry.link_target or "")
        elif _is_sqlite_database(source):
            _copy_sqlite_database(source, target)
        else:
            shutil.copy2(source, target, follow_symlinks=False)


def _run_git(
    project_dir: Path,
    args: list[str],
    *,
    text: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", "-C", str(project_dir), *args],
        capture_output=True,
        text=text,
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
    return {
        "head": head.stdout.strip(),
        "head_ref": symbolic.stdout.strip() if symbolic.returncode == 0 else None,
        "refs": refs.stdout.splitlines(),
        "index_path": str(index_path),
        "index_checksum": _sha256(index_path) if index_path.is_file() else None,
    }


def create_git_recovery_payload(
    project_dir: Path,
    snapshot_dir: Path,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create a bundle and copy the exact Git index into the staged snapshot."""
    recovery_dir = snapshot_dir / RECOVERY_DIR_NAME
    recovery_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "git": None,
        "jj_present": (project_dir / ".jj").exists(),
    }
    if state is not None:
        bundle = recovery_dir / GIT_BUNDLE_NAME
        index_path = Path(str(state["index_path"]))
        saved_index = recovery_dir / GIT_INDEX_NAME
        if index_path.is_file():
            shutil.copy2(index_path, saved_index)
        _create_git_bundle(
            project_dir,
            bundle,
            state,
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
        }
    (recovery_dir / RECOVERY_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def _create_git_bundle(
    project_dir: Path,
    bundle: Path,
    state: dict[str, Any],
    saved_index: Path | None,
) -> None:
    """Bundle refs plus the exact index tree without mutating source refs."""
    index_commit_id: str | None = None
    if saved_index is not None:
        with tempfile.TemporaryDirectory(prefix="backup-git-index-") as temporary:
            working_index = Path(temporary) / "index"
            shutil.copy2(saved_index, working_index)
            index_tree = _run_git(
                project_dir,
                ["write-tree"],
                env={"GIT_INDEX_FILE": str(working_index)},
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
        initialized = _run_git(bundle_repo.parent, ["init", "--bare", str(bundle_repo)])
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
) -> tuple[Path, dict[str, Any]]:
    """Stage a tree and fail closed if source files or Git refs changed."""
    key_excludes: list[str] = []
    candidates = [*sensitive_paths, backup_key_directory()]
    for raw_path in candidates:
        candidate = raw_path.expanduser().resolve(strict=False)
        try:
            key_excludes.append(candidate.relative_to(project_dir.resolve()).as_posix())
        except ValueError:
            continue
    effective_excludes = (*excludes, RECOVERY_DIR_NAME, *key_excludes)
    before = inventory_project_tree(project_dir, effective_excludes, should_exclude)
    git_before = git_state(project_dir)
    if not before and git_before is None:
        raise RuntimeError("Backup source contains no regular files")
    snapshot_dir = staging / "project-snapshot"
    copy_inventory_snapshot(project_dir, snapshot_dir, before)
    recovery = create_git_recovery_payload(project_dir, snapshot_dir, git_before)
    after = inventory_project_tree(project_dir, effective_excludes, should_exclude)
    git_after = git_state(project_dir)
    if before != after or git_before != git_after:
        changed = sorted(set(before) ^ set(after))
        raise RuntimeError(
            "Backup source changed during capture"
            + (f": {', '.join(changed[:5])}" if changed else "")
        )
    recovery.update(
        {
            "snapshot_files": sum(entry.kind == "file" for entry in before.values()),
            "snapshot_symlinks": sum(entry.kind == "symlink" for entry in before.values()),
            "consistent": True,
        }
    )
    manifest_path = snapshot_dir / RECOVERY_DIR_NAME / RECOVERY_MANIFEST_NAME
    manifest_path.write_text(json.dumps(recovery, indent=2, sort_keys=True) + "\n")
    return snapshot_dir, recovery


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
    initialized = _run_git(project_dir, ["init"])
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
