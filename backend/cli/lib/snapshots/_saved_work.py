"""Saved source classification and ownership checks, independent of acceptance locks."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path

from ._helpers import _absolute_git_dir, _git
from ._manifest import _manifest_dir
from ._models import SnapshotError, SnapshotScope

# Rebuildable runtime outputs only. Tracked files always override these defaults.
_DISPOSABLE = {"node_modules", ".venv", "venv", "__pycache__", ".next", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".dev-tools", ".turbo"}


def classifications(root: Path) -> dict[str, list[str]]:
    path = root / "project.identity.json"
    storage = json.loads(path.read_text()).get("storage", {}) if path.is_file() else {}
    result = {}
    for kind in ("durable_data", "disposable_outputs"):
        paths = storage.get(kind, [])
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise SnapshotError(f"storage.{kind} must be a list of relative paths")
        result[kind] = [safe_relative(p) for p in paths]
    return result


def safe_relative(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(p in {"..", ".git"} for p in path.parts):
        raise SnapshotError(f"Unsafe recovery/source path: {value}")
    return path.as_posix()


def beneath(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def file_digest(path: Path) -> str:
    if path.is_symlink():
        return "symlink:" + hashlib.sha256(os.readlink(path).encode()).hexdigest()
    if not path.exists():
        return "missing"
    if not path.is_file():
        raise SnapshotError(f"Selected path is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"{path.stat().st_mode & 0o777:o}:" + digest.hexdigest()


def source_digest(root: Path) -> str:
    tracked = set(_git(root, ["ls-files", "-z"]).stdout.split("\0")) - {""}
    rules = classifications(root)
    paths = set(tracked)
    for current, dirs, files in os.walk(root, followlinks=False):
        rel = Path(current).relative_to(root)
        kept = []
        for directory in dirs:
            item = (rel / directory).as_posix()
            if directory == ".git" or beneath(item, rules["durable_data"]):
                continue
            disposable = directory in _DISPOSABLE or beneath(item, rules["disposable_outputs"])
            if disposable and not any(p.startswith(item + "/") for p in tracked):
                continue
            kept.append(directory)
            if (root / item).is_symlink():
                paths.add(item)
        dirs[:] = kept
        paths.update((rel / file).as_posix() for file in files)
    digest = hashlib.sha256()
    for item in sorted(paths):
        if ".git" in Path(item).parts or beneath(item, rules["durable_data"]):
            continue
        if item not in tracked and (beneath(item, rules["disposable_outputs"]) or any(p in _DISPOSABLE for p in Path(item).parts)):
            continue
        digest.update(item.encode() + b"\0" + file_digest(root / item).encode() + b"\0")
    git_dir = _absolute_git_dir(root)
    for name in ("index", "HEAD"):
        digest.update(name.encode() + b"\0" + file_digest(git_dir / name).encode())
    return digest.hexdigest()


def git_transaction_clear(root: Path) -> None:
    git_dir = _absolute_git_dir(root)
    if any((git_dir / name).exists() for name in ("index.lock", "HEAD.lock", "packed-refs.lock", "config.lock", "shallow.lock")) or any((git_dir / "refs").rglob("*.lock")):
        raise SnapshotError("Deferred: Git index/HEAD/ref transaction is in progress")
    if not (root / ".git").is_dir():
        raise SnapshotError("Deferred: external Git metadata is not inside the captured tree")


@contextlib.contextmanager
def scope_lock(project_id: str, scope: SnapshotScope) -> Iterator[None]:
    with (_manifest_dir(project_id, scope) / "snapshot.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SnapshotError("Deferred: snapshot operation already in progress") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def require_owned(project_id: str, root: Path, paths: list[str], owned_paths: list[str]) -> None:
    from ..leases import identify_agent, list_active
    agent_id, _, session_id, _ = identify_agent()
    leases = list_active(project_id)
    declared = [safe_relative(p) for p in owned_paths]
    claims: dict[str, list[str]] = {}
    for path in paths:
        absolute = str(root / path)
        matching = [lease for lease in leases if lease.matches(absolute)]
        if any(lease.agent_id != agent_id or lease.session_id != session_id for lease in matching):
            raise SnapshotError(f"Foreign ownership blocks recovery: {path}")
        if not beneath(path, declared) or not matching:
            raise SnapshotError(f"An active own lease and declared path are required: {path}")
        permitted = False
        for lease in matching:
            if not lease.task_id:
                continue
            if lease.task_id not in claims:
                claims[lease.task_id] = active_claim_paths(project_id, root, lease.task_id)
            canonical = claims[lease.task_id]
            if not canonical or any(fnmatch(path, pattern) or path.startswith(pattern.rstrip("/") + "/") for pattern in canonical):
                permitted = True
        if not permitted:
            raise SnapshotError(f"Selected path is outside the active task's declared scope: {path}")


def active_claim_paths(project_id: str, root: Path, task_id: str) -> list[str]:
    """Prove the canonical native claim through the configured local owner store."""
    from app.storage.projects import get_project_root_path
    from app.storage.task_spirit import get_task_spirit
    from app.storage.tasks import get_task

    from ..task_claims import _renewal_config, current_worker_id
    try:
        config, local = _renewal_config(root)
        task = get_task(task_id) if local and config.project_id == project_id else None
        registered = get_project_root_path(project_id) if task else None
        if not registered or Path(registered).resolve() != root.resolve() or not task:
            raise SnapshotError("Recovery cannot prove the configured canonical task owner")
        expires = task.get("lock_expires_at")
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        if not expires or task.get("status") != "running" or task.get("claimed_by") != current_worker_id() or expires <= datetime.now(UTC):
            raise SnapshotError("Recovery requires an active canonical task claim owned by this native session")
        spirit = get_task_spirit(task_id) or {}
        context = spirit.get("context") or {}
        return [safe_relative(p) for key in ("files_to_modify", "files_to_create") for p in context.get(key, [])]
    except SnapshotError:
        raise
    except Exception as exc:
        raise SnapshotError(f"Recovery ownership proof unavailable: {exc}") from exc


def apply_file(root: Path, relative: str, source: Path, expected_digest: str) -> None:
    """Use directory descriptors so a swapped symlink parent cannot redirect writes."""
    parts = Path(relative).parts
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, flags)
    temporary = f".sf-recovery-{uuid.uuid4().hex}"
    try:
        for component in parts[:-1]:
            try:
                child = os.open(component, flags, dir_fd=directory)
            except FileNotFoundError:
                os.mkdir(component, dir_fd=directory)
                child = os.open(component, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        destination = Path(f"/proc/self/fd/{directory}") / parts[-1]
        if file_digest(destination) != expected_digest:
            raise SnapshotError("Intervening edit during selected-file apply")
        if not source.exists() and not source.is_symlink():
            if expected_digest != "missing":
                os.unlink(parts[-1], dir_fd=directory)
            return
        if source.is_symlink():
            os.symlink(os.readlink(source), temporary, dir_fd=directory)
        else:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
                for block in iter(lambda: input_file.read(1024 * 1024), b""):
                    output.write(block)
                os.fchmod(output.fileno(), source.stat().st_mode & 0o777)
                output.flush()
                os.fsync(output.fileno())
        if file_digest(destination) != expected_digest:
            raise SnapshotError("Intervening edit during selected-file apply")
        os.replace(temporary, parts[-1], src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)
