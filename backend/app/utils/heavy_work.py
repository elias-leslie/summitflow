"""One same-user lane for transient validation, scans and build work.

This is advisory scheduling, never publication/security authorization. Linux
flock and live ancestor descriptors let nested ST calls share an admission even
when an intermediate subprocess closes inherited descriptors. Resident workers
are never reniced, and no gate, timeout or memory limit is removed or shortened.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils import safe_subprocess

_LOCK_DIRECTORY = Path(f"/tmp/st-heavy-{os.getuid()}")
_LEASE_ENV = "ST_HEAVY_LEASE"
_LOCAL = threading.local()
# The observed 16-CPU/30-GB owner workstation swapped under concurrent suites
# and auto-sized Node/Go pools. Keep one transient job and two internal workers.
WORKERS = 2
WORKER_ENVIRONMENT = (
    "GOMAXPROCS", "RAYON_NUM_THREADS", "UV_THREADPOOL_SIZE", "CARGO_BUILD_JOBS",
    "UV_CONCURRENT_BUILDS", "UV_CONCURRENT_INSTALLS", "UV_CONCURRENT_DOWNLOADS",
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "PYTEST_XDIST_AUTO_NUM_WORKERS",
    "VITEST_MAX_WORKERS", "VITEST_MAX_THREADS", "VITEST_MAX_FORKS",
)


class HeavyWorkError(RuntimeError):
    """Admission infrastructure cannot be validated; work must not bypass it."""


def _process(pid: int) -> tuple[int, str]:
    # comm may contain whitespace/parentheses; remaining stat fields start at 3.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[1]), fields[19]


def _open_lane(name: str) -> int:
    try:
        _LOCK_DIRECTORY.mkdir(mode=0o700, exist_ok=True)
        directory = os.open(_LOCK_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(directory)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise HeavyWorkError("Heavy-work directory must be private and owner-controlled.")
            descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
        finally:
            os.close(directory)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            os.close(descriptor)
            raise HeavyWorkError("Heavy-work lock must be a private regular file.")
        return descriptor
    except OSError as exc:
        raise HeavyWorkError("Heavy-work admission storage is unavailable or unsafe.") from exc


def _inherited(descriptor: int, admission: int, environment: Mapping[str, str]) -> tuple[str, int] | None:
    token = environment.get(_LEASE_ENV, "")
    parts = token.split(":")
    if (len(parts) != 6 or any(not parts[index].isdigit() or len(parts[index]) > 20
                             for index in (0, 1, 3, 4, 5))
            or not re.fullmatch(r"[0-9a-f]{32}", parts[2])):
        return None
    inherited_fd = int(parts[3])
    depth, branch_fd = int(parts[4]), int(parts[5])
    # Same-process owned nesting uses TLS, never a marker borrowed by another
    # thread. A genuine exec/fork descendant has a different generation owner.
    if inherited_fd < 3 or branch_fd < 3 or int(parts[0]) == os.getpid():
        return None
    info = os.fstat(descriptor)
    try:
        generation = ":".join(parts[:3])
        if os.pread(admission, 256, 0).decode("ascii") != generation:
            return None
        pid = os.getpid()
        branch_info = (os.fstat(admission) if depth == 0
                       else (_LOCK_DIRECTORY / f"depth-{depth}.lock").lstat())
        seen: set[int] = set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            parent, started = _process(pid)
            remote = Path(f"/proc/{pid}/fd/{inherited_fd}")
            try:
                holder = remote.stat()
                fdinfo = Path(f"/proc/{pid}/fdinfo/{inherited_fd}").read_text()
                branch_holder = Path(f"/proc/{pid}/fd/{branch_fd}").stat()
                branch_fdinfo = Path(f"/proc/{pid}/fdinfo/{branch_fd}").read_text()
                stable = _process(pid) == (parent, started)
                if (stable and holder.st_uid == os.getuid()
                        and (holder.st_dev, holder.st_ino) == (info.st_dev, info.st_ino)
                        and re.search(r"\bFLOCK\s+ADVISORY\s+READ\b", fdinfo)
                        and (branch_holder.st_dev, branch_holder.st_ino)
                        == (branch_info.st_dev, branch_info.st_ino)
                        and re.search(r"\bFLOCK\s+ADVISORY\s+WRITE\b", branch_fdinfo)):
                    # Acquire our own shared activity lock. This survives any
                    # intermediate close_fds and keeps the next owner waiting
                    # even if every old ancestor exits. The generation cannot
                    # change until all existing shared holders release it.
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    if os.pread(admission, 256, 0).decode("ascii") != generation:
                        return None
                    return generation, depth
            except OSError:
                pass
            pid = parent
    except (OSError, UnicodeError, ValueError):
        return None
    return None


def _bounded(value: str | None, maximum: int = WORKERS) -> str:
    try:
        number = int(value or "")
    except ValueError:
        number = maximum
    return str(min(maximum, number) if number > 0 else maximum)


@dataclass(frozen=True)
class HeavyWork:
    descriptor: int
    token: str
    branch_descriptor: int

    def environment(self, environment: Mapping[str, str] | None = None) -> dict[str, str]:
        result = dict(os.environ if environment is None else environment)
        for key in WORKER_ENVIRONMENT:
            # Vitest's env overrides JS config; one never raises a valid owner
            # maxWorkers=1. Other native tools retain explicit smaller values.
            result[key] = _bounded(result.get(key), 1 if key.startswith("VITEST_") else WORKERS)
        # Next's native default is max(1, CIRCLE_NODE_TOTAL - 1). Explicit
        # next.config cpus overrides remain the owner's configuration.
        result["CIRCLE_NODE_TOTAL"] = _bounded(result.get("CIRCLE_NODE_TOTAL"), WORKERS + 1)
        result[_LEASE_ENV] = self.token
        return result

    def command(self, command: Sequence[str]) -> list[str]:
        result = list(command)
        if not result:
            raise ValueError("heavy-work command cannot be empty")
        # Lower only owned transient children; never permanently alter the
        # Hatchet/ASGI/CLI parent or service runtime process scheduling.
        if ionice := shutil.which("ionice", path=os.defpath):
            # Idle is consistently the lowest native class, including when
            # the caller already inherited idle I/O scheduling.
            result = [ionice, "-t", "-c", "3", *result]
        if nice := shutil.which("nice", path=os.defpath):
            result = [nice, "-n", "10", *result]
        return result

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return (self.descriptor, self.branch_descriptor)

    def run(self, command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        """CLI-only owned child, including its process-group cancellation."""
        check = kwargs.pop("check", False)
        kwargs["env"] = self.environment(kwargs.get("env"))
        # Wrapping with nice/ionice must not hide FileNotFoundError and turn an
        # existing not-applicable missing-tool result into a product failure.
        executable = command[0] if command else ""
        search_path = kwargs["env"].get("PATH", os.defpath)
        if kwargs.get("cwd") is not None:
            child_cwd = os.path.abspath(os.fsdecode(kwargs["cwd"]))
            if os.path.dirname(executable):
                executable = os.path.join(child_cwd, executable)
            search_path = os.pathsep.join(os.path.join(child_cwd, entry) for entry in search_path.split(os.pathsep))
        if command and shutil.which(executable, path=search_path) is None:
            raise FileNotFoundError(command[0])
        observed = safe_subprocess.run_cli_owned(self.command(command), inherit_fds=self.pass_fds, **kwargs)
        result = subprocess.CompletedProcess(list(command), observed.returncode, observed.stdout, observed.stderr)
        if check:
            result.check_returncode()
        return result


@contextmanager
def heavy_work(label: str) -> Iterator[HeavyWork]:
    """Queue heavyweight work; nested contexts/verified descendants reenter."""
    existing = getattr(_LOCAL, "work", None)
    if existing is not None and getattr(_LOCAL, "pid", None) == os.getpid():
        yield existing
        return
    # fork copies TLS but does not create a new execution admission. Its known
    # live parent descriptor token is validated just like an exec descendant.
    environment = dict(os.environ)
    if existing is not None:
        environment[_LEASE_ENV] = existing.token
        del _LOCAL.work
    admission = _open_lane("admission.lock")
    descriptor = None
    branch = None
    try:
        descriptor = _open_lane("activity.lock")
        inherited = _inherited(descriptor, admission, environment)
        if inherited is not None:
            generation, depth = inherited
            depth += 1
            branch = _open_lane(f"depth-{depth}.lock")
            _wait_lock(branch, label)
        else:
            # Owners take these in one order. Descendants join shared activity
            # and the NEXT validated depth: siblings serialize, grandchildren
            # cannot deadlock on a parent's awaited heavy context.
            for lock in (admission, descriptor):
                _wait_lock(lock, label)
            generation = f"{os.getpid()}:{_process(os.getpid())[1]}:{uuid.uuid4().hex}"
            os.ftruncate(admission, 0)
            os.pwrite(admission, generation.encode("ascii"), 0)
            depth, branch = 0, admission
            fcntl.flock(descriptor, fcntl.LOCK_SH)
        token = f"{generation}:{descriptor}:{depth}:{branch}"
        work = HeavyWork(descriptor, token, branch)
        _LOCAL.work, _LOCAL.pid = work, os.getpid()
        try:
            yield work
        finally:
            del _LOCAL.work
    finally:
        # Close, rather than LOCK_UN: an admitted child retains its inherited
        # activity/depth lock until it exits, even if this owner exits abruptly.
        if branch is not None and branch != admission:
            os.close(branch)
        if descriptor is not None:
            os.close(descriptor)
        os.close(admission)


def _wait_lock(descriptor: int, label: str) -> None:
    """Mechanical admission wait; no queue/task policy or timeout shortening."""
    waiting = False
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if waiting:
                print(f"[st] Shared heavy-work lane admitted: {label}", flush=True)
            return
        except BlockingIOError:
            if not waiting:
                print(f"[st] Waiting for shared heavy-work lane: {label}", flush=True)
                waiting = True
            time.sleep(0.1)
