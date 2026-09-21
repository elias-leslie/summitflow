"""Concurrency-safe retained artifacts for ``st check`` tool output."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import suppress
from pathlib import Path

from ..details import detail_path, write_details


def write_check_details(root: Path, name: str, output: str) -> Path:
    """Write one immutable invocation artifact and best-effort latest alias."""
    invocation = f"{time.time_ns():x}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    retained = write_details(root, f"{name}-{invocation}", output)
    latest = detail_path(root, name)
    temporary = latest.with_name(f".{latest.name}-{uuid.uuid4().hex}")
    try:
        temporary.symlink_to(retained.name)
        os.replace(temporary, latest)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
    return retained
