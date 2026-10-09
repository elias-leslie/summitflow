"""One same-user heavy lane and one explicit light slot for transient work.

This is advisory scheduling, never publication/security authorization. Linux
flock and live ancestor descriptors let nested ST calls share an admission even
when an intermediate subprocess closes inherited descriptors. Resident workers
are never reniced, and no gate, timeout or memory limit is removed or shortened.
"""

from __future__ import annotations

import fcntl
import json
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


def _lane_name(name: str, work_class: str) -> str:
    return name if work_class == "heavy" else f"light-{name}"


def _inherited(descriptor: int, admission: int, environment: Mapping[str, str],
               work_class: str = "heavy") -> tuple[str, int] | None:
    token = environment.get(_LEASE_ENV, "")
    if work_class == "light":
        token = token.removeprefix("light:")
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
                       else (_LOCK_DIRECTORY / _lane_name(f"depth-{depth}.lock", work_class)).lstat())
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
    work_class: str = "heavy"
    queue_seconds: float = 0.0

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
def heavy_work(label: str, *, work_class: str = "heavy", project: str | None = None) -> Iterator[HeavyWork]:
    """Queue heavyweight work; nested contexts/verified descendants reenter."""
    if work_class not in {"heavy", "light"}:
        raise HeavyWorkError("Unknown transient-work class.")
    existing = getattr(_LOCAL, "work", None)
    if existing is not None and getattr(_LOCAL, "pid", None) == os.getpid():
        if existing.work_class == "light" and work_class == "heavy":
            raise HeavyWorkError("Light admission cannot be upgraded to heavy work.")
        yield existing
        return
    # fork copies TLS but does not create a new execution admission. Its known
    # live parent descriptor token is validated just like an exec descendant.
    environment = dict(os.environ)
    if existing is not None:
        environment[_LEASE_ENV] = existing.token
        del _LOCAL.work
    requested_class = work_class
    # A verified heavy ancestor covers a nested Ruff stage. A verified light
    # ancestor cannot authorize heavy work, even through an exec/fork boundary.
    inherited_class = "light" if environment.get(_LEASE_ENV, "").startswith("light:") else "heavy"
    work_class = inherited_class if environment.get(_LEASE_ENV) else requested_class
    admission = _open_lane(_lane_name("admission.lock", work_class))
    descriptor = None
    branch = None
    try:
        descriptor = _open_lane(_lane_name("activity.lock", work_class))
        inherited = _inherited(descriptor, admission, environment, work_class)
        if inherited is None and work_class != requested_class:
            new_admission = _open_lane(_lane_name("admission.lock", requested_class))
            try:
                new_descriptor = _open_lane(_lane_name("activity.lock", requested_class))
            except BaseException:
                os.close(new_admission)
                raise
            os.close(descriptor)
            os.close(admission)
            work_class = requested_class
            admission, descriptor = new_admission, new_descriptor
        queued = time.monotonic()
        if inherited is not None:
            if work_class == "light" and requested_class == "heavy":
                raise HeavyWorkError("Light admission cannot be upgraded to heavy work.")
            generation, depth = inherited
            depth += 1
            branch = _open_lane(_lane_name(f"depth-{depth}.lock", work_class))
            _wait_lock(branch, label, work_class=work_class, project=project, activity=descriptor, admission=admission)
        else:
            # Owners take these in one order. Descendants join shared activity
            # and the NEXT validated depth: siblings serialize, grandchildren
            # cannot deadlock on a parent's awaited heavy context.
            _wait_owner(admission, descriptor, label, work_class, project)
            generation = f"{os.getpid()}:{_process(os.getpid())[1]}:{uuid.uuid4().hex}"
            os.ftruncate(admission, 0)
            os.pwrite(admission, generation.encode("ascii"), 0)
            depth, branch = 0, admission
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            _write_holder(work_class, generation, descriptor, label, project)
        token = f"{'light:' if work_class == 'light' else ''}{generation}:{descriptor}:{depth}:{branch}"
        work = HeavyWork(descriptor, token, branch, work_class, time.monotonic() - queued)
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


def _public_label(value: str) -> str:
    # Callers supply operation/project names, never argv, environment or paths.
    return re.sub(r"[^a-zA-Z0-9 ._-]", "?", value)[:80]


@contextmanager
def _metadata() -> Iterator[None]:
    descriptor = _open_lane("queue.lock")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _record(descriptor: int) -> dict[str, Any]:
    try:
        value = json.loads(os.pread(descriptor, 2048, 0))
        if not isinstance(value, dict):
            raise ValueError("invalid record")
        return value
    except (ValueError, UnicodeError) as exc:
        raise HeavyWorkError("Transient-work metadata is invalid.") from exc


def _live_identity(record: dict[str, Any]) -> bool:
    try:
        pid = int(record["pid"])
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0] not in {"Z", "X"} and fields[19] == record["start"]
    except FileNotFoundError:
        return False
    except (OSError, KeyError, ValueError, IndexError) as exc:
        raise HeavyWorkError("Transient-work process identity cannot be verified.") from exc


def _waiters(work_class: str) -> list[str]:
    """Called under metadata lock; never remove a capacity/depth lock."""
    names = []
    for path in _LOCK_DIRECTORY.glob(f"wait-{work_class}-*.json"):
        if not re.fullmatch(rf"wait-{work_class}-[0-9]{{20}}-[0-9a-f]{{32}}\.json", path.name):
            raise HeavyWorkError("Transient-work waiter name is invalid.")
        descriptor = _open_lane(path.name)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                abandoned = True  # Includes death during record creation.
            except BlockingIOError:
                abandoned = not _live_identity(_record(descriptor))
            if abandoned:
                path.unlink()
            else:
                names.append(path.name)
        finally:
            os.close(descriptor)
    return sorted(names)


def _identity(label: str, project: str | None) -> dict[str, Any]:
    return {"pid": os.getpid(), "start": _process(os.getpid())[1],
            "label": _public_label(label), "project": _public_label(project or Path.cwd().name),
            "since": time.monotonic()}


def _write_holder(work_class: str, generation: str, activity: int, label: str, project: str | None) -> None:
    with _metadata():
        descriptor = _open_lane(f"{work_class}-holder.json")
        try:
            record = {**_identity(label, project), "generation": generation, "fd": activity}
            content = json.dumps(record).encode("ascii")
            os.pwrite(descriptor, content, 0)
            os.ftruncate(descriptor, len(content))
        finally:
            os.close(descriptor)


def _wait_status(work_class: str, label: str, since: float, activity: int, admission: int) -> None:
    holder = "holder=unknown"
    with _metadata():
        descriptor = _open_lane(f"{work_class}-holder.json")
        try:
            try:
                record = _record(descriptor)
                pid, fd = int(record["pid"]), int(record["fd"])
                remote = Path(f"/proc/{pid}/fd/{fd}").stat()
                local = os.fstat(activity)
                fdinfo = Path(f"/proc/{pid}/fdinfo/{fd}").read_text()
                if (_live_identity(record) and (remote.st_dev, remote.st_ino) == (local.st_dev, local.st_ino)
                        and re.search(r"\bFLOCK\s+ADVISORY\s+READ\b", fdinfo)
                        and os.pread(admission, 256, 0).decode("ascii") == record["generation"]):
                    holder = (f"holder={_public_label(record['label'])} project={_public_label(record['project'])} "
                              f"pid={pid} active_age={max(0, time.monotonic() - float(record['since'])):.1f}s")
            except (HeavyWorkError, OSError, KeyError, ValueError, TypeError, UnicodeError):
                pass  # Legacy owners or surviving descendants may lack metadata.
        finally:
            os.close(descriptor)
    print(f"[st] Waiting for shared {work_class}-work lane: {_public_label(label)} "
          f"class={work_class} wait_age={time.monotonic() - since:.1f}s {holder}", flush=True)


def _wait_owner(admission: int, activity: int, label: str, work_class: str, project: str | None) -> None:
    waiter = None
    name = None
    since = time.monotonic()
    try:
        with _metadata():
            names = _waiters(work_class)
            order = max(time.monotonic_ns(), int(names[-1].split("-")[2]) + 1 if names else 0)
            name = f"wait-{work_class}-{order:020d}-{uuid.uuid4().hex}.json"
            waiter = _open_lane(name)
            fcntl.flock(waiter, fcntl.LOCK_EX)
            os.pwrite(waiter, json.dumps(_identity(label, project)).encode("ascii"), 0)
        next_status = since
        while True:
            with _metadata():
                if _waiters(work_class)[0] == name:
                    try:
                        fcntl.flock(admission, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        try:
                            fcntl.flock(activity, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            # No child was launched on this admission. Releasing
                            # our own EX lock cannot release descendant activity.
                            fcntl.flock(admission, fcntl.LOCK_UN)
                        else:
                            (_LOCK_DIRECTORY / name).unlink()
                            name = None
                            return
            if time.monotonic() >= next_status:
                _wait_status(work_class, label, since, activity, admission)
                next_status = time.monotonic() + 5
            time.sleep(0.1)
    finally:
        try:
            if name is not None:
                with _metadata():
                    (_LOCK_DIRECTORY / name).unlink(missing_ok=True)
        finally:
            if waiter is not None:
                os.close(waiter)


def _wait_lock(descriptor: int, label: str, *, work_class: str = "heavy", project: str | None = None,
               activity: int, admission: int) -> None:
    """Verified descendant branches retain their established depth semantics."""
    since = time.monotonic()
    next_status = since
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= next_status:
                _wait_status(work_class, label, since, activity, admission)
                next_status = time.monotonic() + 5
            time.sleep(0.1)
