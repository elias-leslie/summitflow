"""Subprocess helpers safe for ASGI request/service paths."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

StrPath = str | os.PathLike[str]


def _resolve_executable(executable: str, env: Mapping[str, str] | None = None) -> str:
    path = Path(executable).expanduser()
    if path.is_absolute():
        return str(path)
    if os.sep in executable:
        resolved = path.resolve()
        if resolved.exists():
            return str(resolved)
        raise FileNotFoundError(executable)
    found = shutil.which(executable, path=(env or os.environ).get("PATH"))
    if found:
        return found
    raise FileNotFoundError(executable)


def _argv(args: Sequence[StrPath], env: Mapping[str, str] | None = None) -> list[str]:
    argv = [str(arg) for arg in args]
    if not argv:
        raise ValueError("subprocess args cannot be empty")
    argv[0] = _resolve_executable(argv[0], env)
    return argv


def _with_chdir(argv: list[str], cwd: StrPath | None, env: Mapping[str, str] | None) -> list[str]:
    if cwd is None:
        return argv
    env_bin = _resolve_executable("env", env)
    return [env_bin, "-C", str(Path(cwd)), *argv]


def run(args: Sequence[StrPath], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Run a command without Python fork from a web worker.

    Python's subprocess can fork when cwd/fd/session options are present. This
    wrapper keeps Python on the posix_spawn path by using an absolute executable,
    close_fds=False, and GNU env -C for child cwd changes.
    """
    if kwargs.get("preexec_fn") is not None:
        raise ValueError("preexec_fn is not safe in ASGI subprocess calls")
    if kwargs.get("start_new_session"):
        raise ValueError("start_new_session is not safe in ASGI subprocess calls")
    shell = kwargs.pop("shell", False)
    if shell is not False:
        raise ValueError("shell execution is not allowed in ASGI subprocess calls")
    close_fds = kwargs.pop("close_fds", False)
    if close_fds is not False:
        raise ValueError("close_fds must be False in ASGI subprocess calls")
    cwd = kwargs.pop("cwd", None)
    env = kwargs.get("env")
    argv = _with_chdir(_argv(args, env), cwd, env)
    return subprocess.run(argv, close_fds=False, shell=False, **kwargs)


async def run_async(args: Sequence[StrPath], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Async adapter for safe subprocess calls."""
    return await asyncio.to_thread(run, args, **kwargs)


@dataclass
class PipeProcess:
    """Small posix_spawn process wrapper with stdout pipe support."""

    pid: int
    stdout_fd: int
    returncode: int | None = None
    _stdout_file: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._stdout_file = os.fdopen(self.stdout_fd, "rb", buffering=0)

    async def readline(self) -> bytes:
        return await asyncio.to_thread(self._stdout_file.readline)

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        with contextlib.suppress(ChildProcessError):
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.returncode = _wait_status_to_returncode(status)
        return self.returncode

    async def wait(self) -> int:
        if self.returncode is None:
            _pid, status = await asyncio.to_thread(os.waitpid, self.pid, 0)
            self.returncode = _wait_status_to_returncode(status)
        return self.returncode

    def kill(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(self.pid, signal.SIGKILL)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._stdout_file.close()


def _wait_status_to_returncode(status: int) -> int:
    if os.WIFSIGNALED(status):
        return -os.WTERMSIG(status)
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    return status


def spawn_pipe(
    args: Sequence[StrPath],
    *,
    cwd: StrPath | None = None,
    env: Mapping[str, str] | None = None,
    stderr_to_stdout: bool = False,
) -> PipeProcess:
    """Spawn a long-running command with stdout pipe without Python fork."""
    stdout_r, stdout_w = os.pipe()
    argv = _with_chdir(_argv(args, env), cwd, env)
    actions = [
        (os.POSIX_SPAWN_DUP2, stdout_w, 1),
        (os.POSIX_SPAWN_CLOSE, stdout_r),
        (os.POSIX_SPAWN_CLOSE, stdout_w),
    ]
    if stderr_to_stdout:
        actions.append((os.POSIX_SPAWN_DUP2, 1, 2))
    try:
        pid = os.posix_spawn(argv[0], argv, dict(env or os.environ), file_actions=actions)
    except Exception:
        os.close(stdout_r)
        os.close(stdout_w)
        raise
    os.close(stdout_w)
    return PipeProcess(pid=pid, stdout_fd=stdout_r)
