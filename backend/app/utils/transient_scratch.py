"""Private transient storage on the host's excluded disposable mount."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

SCRATCH_ROOT = Path("/srv/scratch")
_ACTIVE_SCRATCH: ContextVar[Path | None] = ContextVar("active_disposable_scratch", default=None)


class ScratchError(RuntimeError):
    """Transient staging cannot safely use its required scratch destination."""


def current_scratch() -> Path | None:
    """Return the currently owned disposable binding for optional integrations."""
    return _ACTIVE_SCRATCH.get()


def validate_temp_parent(path: Path, *, private: bool = False, label: str = "Restore") -> None:
    """Validate without changing permissions or following directory aliases."""
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError(f"{label} temporary directory must be absolute and not a symlink")
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.getuid()}:
        raise ValueError(f"{label} temporary directory must be owner-controlled")
    if private:
        if info.st_uid != os.getuid() or mode != 0o700:
            raise ValueError(f"{label} scratch directory must be private and owned by the current user")
    elif mode & 0o022 and not mode & stat.S_ISVTX:
        raise ValueError(f"{label} shared temporary directory requires the sticky bit")


def mounted_scratch_parent(
    namespace: str, *, root: Path | None = None, required: bool = True, label: str = "Restore",
) -> Path | None:
    """Only cleanrooms opt into portability; restores require the known mount."""
    root = SCRATCH_ROOT if root is None else root
    if not required and not root.exists() and not root.is_symlink():
        return None
    if not namespace or Path(namespace).name != namespace or namespace in {".", ".."}:
        raise ValueError("Scratch namespace must be a single directory name")
    try:
        validate_temp_parent(root, label=label)
        if not root.is_mount() or root.stat().st_mode & 0o022:
            raise ValueError(f"{label} scratch root must be a mounted, owner-controlled directory")
        parent = root / f"{namespace}-{os.getuid()}"
        parent.mkdir(mode=0o700, exist_ok=True)
        validate_temp_parent(parent, private=True, label=label)
        return parent
    except (OSError, ValueError) as exc:
        if not required:
            raise
        raise ScratchError(f"Restore scratch is unavailable or unsafe at {root}: {exc}") from exc


def ensure_scratch_capacity(path: Path, additional_bytes: int) -> None:
    """Budget additional known bytes against actual destination free space."""
    from app.tasks._retention_policy import HostRetentionPolicy

    if additional_bytes < 0:
        raise ValueError("Restore staging byte requirement cannot be negative")
    reserve = int(HostRetentionPolicy.from_env().pressure_min_free_gb * 1024**3)
    if reserve < 0:
        raise ScratchError("Restore scratch reserve cannot be negative")
    free = shutil.disk_usage(path).free
    if free - additional_bytes < reserve:
        raise ScratchError(
            f"Insufficient restore scratch space at {path}: {free} bytes free, "
            f"{additional_bytes} additional known bytes required, {reserve} bytes reserved"
        )


def tree_bytes(root: Path) -> int:
    """Count materialized regular-file bytes without following saved links."""
    return sum(info.st_size for path in root.rglob("*")
               if stat.S_ISREG((info := path.lstat()).st_mode))


@contextmanager
def bind_scratch(path: Path) -> Iterator[Path]:
    """Bind an already owned private capture without removing its reusable state."""
    validate_temp_parent(path, private=True, label="Transient")
    parent = mounted_scratch_parent("st-backups")
    assert parent is not None
    if not path.is_relative_to(parent.parent):
        raise ScratchError("Transient job must be inside the required scratch mount")
    ensure_scratch_capacity(path, 0)
    token = _ACTIVE_SCRATCH.set(path)
    try:
        yield path
    finally:
        _ACTIVE_SCRATCH.reset(token)


@contextmanager
def disposable_scratch(
    prefix: str, *, namespace: str = "st-backups", required_bytes: int = 0,
) -> Iterator[Path]:
    """Own a private job on the admitted mount, including nested process work."""
    parent = mounted_scratch_parent(namespace)
    assert parent is not None
    ensure_scratch_capacity(parent, required_bytes)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=parent) as directory:
        job = Path(directory)
        token = _ACTIVE_SCRATCH.set(job)
        try:
            yield job
        finally:
            _ACTIVE_SCRATCH.reset(token)


@contextmanager
def subprocess_scratch() -> Iterator[Path]:
    """Reuse the current job, or own a short process job for standalone callers."""
    job = _ACTIVE_SCRATCH.get()
    if job is None:
        with disposable_scratch("backup-process-") as owned:
            yield owned
    else:
        validate_temp_parent(job, private=True, label="Transient")
        ensure_scratch_capacity(job, 0)
        yield job


def scratch_subprocess_env(
    env: dict[str, str] | None = None, *, path: Path | None = None,
) -> dict[str, str]:
    """Route child temp/cache writes inside the current owned job, without global changes."""
    result = dict(os.environ) if env is None else dict(env)
    job = path if path is not None else _ACTIVE_SCRATCH.get()
    if job is None:
        return result
    if path is not None:
        parent = mounted_scratch_parent("st-backups")
        assert parent is not None
        if not job.is_relative_to(parent.parent):
            raise ScratchError("Transient process work must be inside the required scratch mount")
    validate_temp_parent(job, private=True, label="Transient")
    ensure_scratch_capacity(job, 0)
    for name in ("tmp", "cache"):
        child = job / name
        child.mkdir(mode=0o700, exist_ok=True)
        validate_temp_parent(child, private=True, label="Transient")
    result.update(TMPDIR=str(job / "tmp"), TMP=str(job / "tmp"), TEMP=str(job / "tmp"),
                  XDG_CACHE_HOME=str(job / "cache"))
    return result


@contextmanager
def restore_scratch(prefix: str, *, required_bytes: int = 0) -> Iterator[Path]:
    """No inherited TMPDIR or root-volume fallback for plaintext restore work."""
    with disposable_scratch(prefix, namespace="st-restores", required_bytes=required_bytes) as job:
        yield job
