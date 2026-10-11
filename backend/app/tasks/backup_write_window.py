"""Open the T7 write window around backup work (see scripts/summitflow-backup-window).

Backup storage on the T7 is read-only outside these windows, so an accidental
``rm`` or stray write from any other process fails. Windows are reference
counted per process: nested and concurrent users share one helper ``open``
and the last one out calls ``close``. Without the helper (tests, other hosts)
this is a no-op; a helper failure is logged and the job proceeds, failing
naturally if the storage stays read-only.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

from ..logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_HELPER = "/usr/local/sbin/summitflow-backup-window"
PROTECTED = {"t7": Path("/media/kasadis/Backups/davion-gem"), "native": Path("/mnt/summitflow-native")}
_lock = threading.Lock()
_counts: dict[str, int] = {}


def _helper() -> str | None:
    helper = os.environ.get("SUMMITFLOW_BACKUP_WINDOW_HELPER", DEFAULT_HELPER)
    return helper if helper and Path(helper).is_file() else None


def window_name(path: str | Path) -> str | None:
    candidate = Path(os.path.abspath(path))
    for name, root in PROTECTED.items():
        if candidate == root or candidate.is_relative_to(root):
            return name
    return None


def _call(action: str, name: str) -> None:
    helper = _helper()
    if helper is None:
        return
    try:
        subprocess.run(["sudo", "-n", helper, action, name, str(os.getpid())], check=True,
                       capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("backup_write_window_failed", action=action, window=name, error=str(exc))


@contextlib.contextmanager
def write_window(name: str | None) -> Iterator[None]:
    if name is None:
        yield
        return
    with _lock:
        _counts[name] = _counts.get(name, 0) + 1
        if _counts[name] == 1:
            _call("open", name)
    try:
        yield
    finally:
        with _lock:
            _counts[name] -= 1
            if _counts[name] == 0:
                _call("close", name)


def path_window(path: str | Path) -> contextlib.AbstractContextManager[None]:
    """Window for whichever protected tree contains ``path`` (none if unprotected)."""
    return write_window(window_name(path))
