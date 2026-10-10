"""Native ASGI subprocess helpers and an explicitly separate CLI-owned adapter."""

from __future__ import annotations

import asyncio
import contextlib
import os
import selectors
import shutil
import signal
import subprocess
import time
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


def _stop_cli_owned_process(process: subprocess.Popen[Any]) -> None:
    """Cancel only the CLI's captured owned subtree, including new sessions."""
    def identity(pid: int) -> tuple[int, int, str]:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[1]), int(fields[2]), fields[19]

    snapshot: dict[int, tuple[int, int, str]] = {}

    def alive(pid: int) -> bool:
        try:
            return pid in snapshot and identity(pid)[2] == snapshot[pid][2]
        except (OSError, ValueError):
            return False

    def signal_owned(sig: int, owned: set[int]) -> None:
        # The initial group remains ours after its leader exits. Pipe-holding
        # children must not defeat timeout, but unrelated groups are not ours.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, sig)
        for pid in [*sorted(owned - {process.pid}), process.pid]:
            if alive(pid):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, sig)

    # Freeze before signaling: a live owner can fork a new-session child after
    # a /proc scan and then die, orphaning it outside the captured subtree.
    # Stopped processes cannot fork, so rescanning until no new owned process
    # appears captures the whole subtree while parent links still hold.
    owned = {process.pid}
    stopped: set[int] = set()
    while True:
        current: dict[int, tuple[int, int, str]] = {}
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                with contextlib.suppress(OSError, ValueError):
                    current[int(entry.name)] = identity(int(entry.name))
        # Owned identities stay pinned to first sight, so a reused PID is never signaled.
        snapshot = {**current, **{pid: snapshot[pid] for pid in owned if pid in snapshot}}
        # Group members whose parent exited are still ours, as are their children.
        owned |= {pid for pid, (_parent, group, _start) in snapshot.items() if group == process.pid}
        while additions := {pid for pid, (parent, _group, _start) in snapshot.items() if parent in owned} - owned:
            owned.update(additions)
        if owned <= stopped:
            break
        stopped |= owned
        signal_owned(signal.SIGSTOP, owned)

    for sig in (signal.SIGTERM, signal.SIGKILL):
        signal_owned(sig, owned)
        if sig == signal.SIGTERM:
            # Stopped owners must resume to act on SIGTERM, e.g. reap children.
            signal_owned(signal.SIGCONT, owned)
        try:
            process.communicate(timeout=2)
            if not any(alive(pid) for pid in owned - {process.pid}):
                return
        except subprocess.TimeoutExpired:
            pass
    # Already-reparented detached sessions are outside the captured subtree.
    # Bound the final drain; never broaden signaling to unrelated processes.
    try:
        process.communicate(timeout=0)
    except subprocess.TimeoutExpired:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        process.wait(timeout=2)


def run_cli_owned(
    args: Sequence[StrPath], *, inherit_fds: Sequence[int], **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """CLI only: own a new session and its synchronous capture/timeout cleanup.

    Unlike run()/run_inherited(), this may use Python fork. Resident ASGI/task
    callers must keep using those native-spawn adapters, never this one.
    """
    if kwargs.pop("shell", False) or kwargs.get("preexec_fn") is not None:
        raise ValueError("Owned CLI execution requires argv without preexec_fn")
    if "pass_fds" in kwargs or "start_new_session" in kwargs:
        raise ValueError("Owned CLI execution controls descriptor and session ownership")
    check = kwargs.pop("check", False)
    timeout = kwargs.pop("timeout", None)
    data = kwargs.pop("input", None)
    if kwargs.pop("capture_output", False):
        if "stdout" in kwargs or "stderr" in kwargs:
            raise ValueError("capture_output conflicts with stdout or stderr")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if data is not None:
        if "stdin" in kwargs:
            raise ValueError("stdin and input cannot both be supplied")
        kwargs["stdin"] = subprocess.PIPE
    argv = _argv(args, kwargs.get("env"))
    with subprocess.Popen(argv, pass_fds=inherit_fds, start_new_session=True, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(data, timeout=timeout)
        except BaseException:
            _stop_cli_owned_process(process)
            raise
    result = subprocess.CompletedProcess(list(args), process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result


def run_inherited(
    args: Sequence[StrPath], *, inherit_fds: Sequence[int],
    env: Mapping[str, str] | None = None, timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Capture an owned scan with explicit lease FDs, still without Python fork.

    DUP2 of the descriptor onto itself clears CLOEXEC only in the spawned child.
    No temporary parent-inheritable descriptor leaks into unrelated services.
    This narrow byte-output adapter is not a replacement for general run().
    """
    argv = _argv(args, env)
    pipes = [os.pipe(), os.pipe()]
    identities = {fd: (os.fstat(fd).st_dev, os.fstat(fd).st_ino) for pair in pipes for fd in pair}
    pid = None
    readers: set[int] = set()
    outputs: dict[int, list[bytes]] = {read: [] for read, _write in pipes}
    status = None
    deadline = time.monotonic() + timeout if timeout is not None else None
    try:
        actions: list[tuple[int, int] | tuple[int, int, int]] = [
            (os.POSIX_SPAWN_DUP2, fd, fd) for fd in dict.fromkeys(inherit_fds)
        ]
        actions.extend((os.POSIX_SPAWN_DUP2, write, target)
                       for (_read, write), target in zip(pipes, (1, 2), strict=True))
        actions.extend((os.POSIX_SPAWN_CLOSE, fd) for pair in pipes for fd in pair)
        pid = os.posix_spawn(argv[0], argv, dict(os.environ if env is None else env),
                             file_actions=actions, setpgroup=0)
        for read, write in pipes:
            os.close(write)
            readers.add(read)
        with selectors.DefaultSelector() as selector:
            for read in readers:
                selector.register(read, selectors.EVENT_READ)
            while readers or status is None:
                if deadline is not None and time.monotonic() >= deadline:
                    assert timeout is not None
                    raise subprocess.TimeoutExpired(argv, timeout)
                delay = min(0.1, max(0, deadline - time.monotonic())) if deadline is not None else 0.1
                for key, _events in selector.select(delay):
                    data = os.read(key.fd, 65536)
                    if data:
                        outputs[key.fd].append(data)
                    else:
                        selector.unregister(key.fd)
                        readers.remove(key.fd)
                        os.close(key.fd)
                if status is None:
                    completed, observed = os.waitpid(pid, os.WNOHANG)
                    if completed:
                        status = observed
        assert status is not None
        return subprocess.CompletedProcess(list(args), _wait_status_to_returncode(status),
                                           b"".join(outputs[pipes[0][0]]), b"".join(outputs[pipes[1][0]]))
    except BaseException:
        if pid is not None:
            # Only the owned native scanner group; never an app/worker group.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
            if status is None:
                with contextlib.suppress(ChildProcessError):
                    os.waitpid(pid, 0)
        raise
    finally:
        for pair in pipes:
            for fd in pair:
                # A just-closed FD can be reused by another web thread even
                # during cancellation. Never close its unrelated replacement.
                with contextlib.suppress(OSError):
                    current = os.fstat(fd)
                    if (current.st_dev, current.st_ino) == identities[fd]:
                        os.close(fd)


@dataclass
class PipeProcess:
    """Small posix_spawn process wrapper with stdout pipe support."""

    pid: int
    stdout_fd: int
    returncode: int | None = None
    stdin_fd: int | None = None
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

    def terminate(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(self.pid, signal.SIGTERM)

    def close_stdin(self) -> None:
        """Signal EOF to an owned duplex process without writing user input."""
        if self.stdin_fd is not None:
            os.close(self.stdin_fd)
            self.stdin_fd = None

    def close(self) -> None:
        self.close_stdin()
        with contextlib.suppress(Exception):
            self._stdout_file.close()


def spawn_duplex(
    args: Sequence[StrPath], *, env: Mapping[str, str] | None = None,
) -> PipeProcess:
    """Spawn an EOF-controlled owner lease, with private stdout and no stderr log."""
    stdin_r, stdin_w = os.pipe()
    stdout_r, stdout_w = os.pipe()
    stderr_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        argv = _argv(args, env)
        actions = [
            (os.POSIX_SPAWN_DUP2, stdin_r, 0),
            (os.POSIX_SPAWN_DUP2, stdout_w, 1),
            (os.POSIX_SPAWN_DUP2, stderr_fd, 2),
            *((os.POSIX_SPAWN_CLOSE, fd) for fd in (stdin_r, stdin_w, stdout_r, stdout_w, stderr_fd)),
        ]
        pid = os.posix_spawn(argv[0], argv, dict(env or os.environ), file_actions=actions)
    except BaseException:
        for fd in (stdin_r, stdin_w, stdout_r, stdout_w, stderr_fd):
            os.close(fd)
        raise
    for fd in (stdin_r, stdout_w, stderr_fd):
        os.close(fd)
    return PipeProcess(pid=pid, stdout_fd=stdout_r, stdin_fd=stdin_w)


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
