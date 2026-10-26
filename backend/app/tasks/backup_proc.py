"""Run one backup command with a deadline, holding its output in memory only.

Backups must never depend on free disk for their own bookkeeping, so nothing here
touches a temporary file. The process runs in its own group; at the deadline it is
interrupted (restic then removes its repository lock), then terminated, then killed.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TAIL_LINES = 40
MAX_CAPTURED_LINES = 200_000


@dataclass
class Result:
    returncode: int
    summary: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        # restic exits 3 after saving a snapshot when some files vanished or could not be read.
        return self.returncode == 0 or (self.returncode == 3 and bool(self.summary))


def run_process(command: Sequence[str], *, env: Mapping[str, str] | None, timeout: float, capture: bool = False,
                on_line: Callable[[str], None] | None = None) -> Result:
    """Run ``command`` for at most ``timeout`` seconds. ``capture`` keeps all of stdout, otherwise only its last lines."""
    proc = subprocess.Popen(list(command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=None if env is None else dict(env), start_new_session=True, text=True, errors="replace")
    summary: dict[str, Any] = {}
    lines: deque[str] = deque(maxlen=MAX_CAPTURED_LINES if capture else TAIL_LINES)
    errors: deque[str] = deque(maxlen=TAIL_LINES)

    def read_stdout() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line.startswith("{"):
                try:
                    message = json.loads(line)
                except ValueError:
                    message = None
                if isinstance(message, dict) and message.get("message_type") == "summary":
                    summary.clear()
                    summary.update(message)
                    continue
                if isinstance(message, dict) and message.get("message_type") in {"status", "verbose_status"}:
                    continue
            lines.append(line if capture else line[:2000])
            if on_line is not None:
                on_line(line)

    def read_stderr() -> None:
        assert proc.stderr is not None
        for raw in proc.stderr:
            errors.append(raw.rstrip("\n")[:2000])

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for reader in readers:
        reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop(proc)
        for reader in readers:
            reader.join(5)
        return Result(124, summary, "\n".join(lines), f"timed out after {int(timeout)}s\n" + "\n".join(errors))
    except BaseException:
        stop(proc)
        raise
    for reader in readers:
        reader.join(30)
    return Result(proc.returncode, summary, "\n".join(lines), "\n".join(errors))


def stop(proc: subprocess.Popen[Any]) -> None:
    """Interrupt, terminate, then kill the whole process group (sudo relays the first two to its root child)."""
    for sig, grace in ((signal.SIGINT, 30), (signal.SIGTERM, 10)):
        if proc.poll() is not None:
            break
        try:
            os.killpg(proc.pid, sig)
            proc.wait(timeout=grace)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            continue
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
