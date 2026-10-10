from __future__ import annotations

import subprocess
import sys

import pytest

from app.utils import safe_subprocess


def test_run_resolves_executable_uses_env_chdir_and_disables_close_fds(monkeypatch) -> None:
    completed = subprocess.CompletedProcess([], 0, "", "")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_which(name: str, path: str | None = None) -> str:
        assert path is not None
        return f"/usr/bin/{name}"

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return completed

    monkeypatch.setattr(safe_subprocess.shutil, "which", fake_which)
    monkeypatch.setattr(safe_subprocess.subprocess, "run", fake_run)

    assert safe_subprocess.run(["git", "status"], cwd="/repo", capture_output=True) is completed
    assert calls == [
        (
            ["/usr/bin/env", "-C", "/repo", "/usr/bin/git", "status"],
            {"capture_output": True, "close_fds": False, "shell": False},
        )
    ]


def test_run_rejects_fork_forcing_options() -> None:
    with pytest.raises(ValueError, match="preexec_fn"):
        safe_subprocess.run(["git"], preexec_fn=lambda: None)

    with pytest.raises(ValueError, match="start_new_session"):
        safe_subprocess.run(["git"], start_new_session=True)

    with pytest.raises(ValueError, match="close_fds"):
        safe_subprocess.run(["git"], close_fds=True)

    with pytest.raises(ValueError, match="shell execution"):
        safe_subprocess.run(["git status"], shell=True)


@pytest.mark.asyncio
async def test_duplex_owner_receives_eof_and_is_reaped() -> None:
    process = safe_subprocess.spawn_duplex([
        sys.executable, "-c", "import sys; print('ready', flush=True); sys.stdin.read(); print('released', flush=True)",
    ])
    try:
        assert await process.readline() == b"ready\n"
        assert process.poll() is None
        process.close_stdin()
        process.close_stdin()
        assert await process.readline() == b"released\n"
        assert await process.wait() == 0
        assert process.poll() == 0
    finally:
        process.close()


def _open_pipes() -> set[tuple[str, str]]:
    """Snapshot this process's open pipe descriptors by (fd, kernel pipe identity).

    A bare descriptor count is shared with the whole pytest process: an
    unreferenced file or transport left by an earlier test can be finalized by
    the garbage collector (or another thread) mid-measurement and lower the
    count, which made these leak checks flaky (89 != 90). The helpers under test
    only create pipes, and each new pipe has a fresh ``pipe:[inode]`` identity,
    so a reused descriptor number still shows up as a leak.
    """
    import os

    pipes: set[tuple[str, str]] = set()
    for fd in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:  # the listdir descriptor itself, or one closed concurrently
            continue
        if target.startswith("pipe:"):
            pipes.add((fd, target))
    return pipes


def _baseline_pipes() -> set[tuple[str, str]]:
    import gc

    gc.collect()  # finalize earlier tests' garbage before taking the baseline
    return _open_pipes()


def test_duplex_spawn_failure_closes_all_pipe_descriptors(monkeypatch) -> None:
    before = _baseline_pipes()
    with pytest.raises(FileNotFoundError):
        safe_subprocess.spawn_duplex(["/does/not/exist"])
    assert _open_pipes() - before == set()


def test_inherited_scan_uses_native_spawn_and_preserves_explicit_lease_fds(tmp_path, monkeypatch) -> None:
    import os

    from app.utils import heavy_work as guard

    directory = tmp_path / "lane"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", directory)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("ASGI scan must not use Popen/fork/preexec")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    code = (
        "import sys,os; from pathlib import Path; "
        "from app.utils import heavy_work as guard; "
        f"guard._LOCK_DIRECTORY=Path({str(directory)!r});\n"
        "with guard.heavy_work('native descendant'): print('ok',flush=True)\n"
        "sys.stderr.write('diagnostic')\n"
    )
    before = os.getpriority(os.PRIO_PROCESS, 0)
    with guard.heavy_work("ASGI fixture") as work:
        result = safe_subprocess.run_inherited(work.command([sys.executable, "-c", code]),
                                               inherit_fds=work.pass_fds, env=work.environment(), timeout=5)
    assert result.returncode == 0 and result.stdout == b"ok\n" and result.stderr == b"diagnostic"
    assert os.getpriority(os.PRIO_PROCESS, 0) == before


def test_inherited_spawn_failure_and_timeout_reap_owned_resources(monkeypatch) -> None:
    before = _baseline_pipes()
    with pytest.raises(FileNotFoundError):
        safe_subprocess.run_inherited(["/does/not/exist"], inherit_fds=())
    assert _open_pipes() - before == set()
    with pytest.raises(subprocess.TimeoutExpired):
        safe_subprocess.run_inherited([sys.executable, "-c", "import time; time.sleep(60)"],
                                     inherit_fds=(), timeout=0.1)
    assert _open_pipes() - before == set()


@pytest.mark.parametrize("adapter", ["native", "cli"])
def test_timeout_stops_pipe_child_after_owned_leader_exits(tmp_path, adapter) -> None:
    # Keep subreaper state inside an isolated fixture process, never pytest or
    # the resident worker. A departed leader must not defeat the pipe deadline.
    code = f"""
import ctypes, os, signal, subprocess, sys, time
from pathlib import Path
from app.utils import heavy_work as guard, safe_subprocess
assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
guard._LOCK_DIRECTORY = Path({str(tmp_path / 'lane')!r})
child_code = "import os,time; pid=os.fork(); os._exit(0) if pid else time.sleep(60)"
started = time.monotonic()
# This Python's UUID implementation lazily caches /dev/urandom. Admission's
# first generation must not count that stdlib descriptor as an adapter leak.
guard.uuid.uuid4()
before = len(os.listdir('/proc/self/fd'))
with guard.heavy_work('departed leader fixture') as work:
    try:
        if {adapter!r} == 'native':
            safe_subprocess.run_inherited(work.command([sys.executable, '-c', child_code]),
                inherit_fds=work.pass_fds, env=work.environment(), timeout=0.3)
        else:
            work.run([sys.executable, '-c', child_code], capture_output=True, timeout=0.3)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError('deadline was not preserved')
assert time.monotonic() - started < 4
pid, status = os.waitpid(-1, 0)
assert pid > 0 and os.WIFSIGNALED(status)
assert os.WTERMSIG(status) in (signal.SIGTERM, signal.SIGKILL)
after = len(os.listdir('/proc/self/fd'))
assert after == before, (before, after, [(fd, os.readlink('/proc/self/fd/' + fd))
    for fd in os.listdir('/proc/self/fd') if os.path.exists('/proc/self/fd/' + fd)])
print('reaped', flush=True)
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=8)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "reaped\n"


def test_cli_timeout_does_not_wait_forever_for_reparented_detached_pipe(tmp_path) -> None:
    marker = tmp_path / "detached-pid"
    child_code = (
        "import os,time; from pathlib import Path; pid=os.fork(); "
        "os._exit(0) if pid else None; os.setsid(); "
        f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    driver = f"""
import ctypes, os, signal, subprocess, sys, time
from pathlib import Path
from app.utils import heavy_work as guard
assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
guard._LOCK_DIRECTORY = Path({str(tmp_path / 'lane')!r})
started = time.monotonic()
try:
    with guard.heavy_work('detached fixture') as work:
        try:
            work.run([sys.executable, '-c', {child_code!r}], capture_output=True, timeout=0.3)
        except subprocess.TimeoutExpired as exc:
            assert exc.timeout == 0.3
        else:
            raise AssertionError('deadline was lost')
    assert time.monotonic() - started < 7
    pid = int(Path({str(marker)!r}).read_text())
    assert Path('/proc/' + str(pid)).exists(), 'must not broaden cancellation'
finally:
    if Path({str(marker)!r}).exists():
        pid = int(Path({str(marker)!r}).read_text())
        os.kill(pid, signal.SIGKILL)
        assert os.waitpid(pid, 0)[0] == pid
print('bounded and reaped', flush=True)
"""
    completed = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "bounded and reaped\n"


def test_cli_owned_adapter_preserves_input_capture_and_check() -> None:
    command = [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read()); sys.exit(3)"]
    result = safe_subprocess.run_cli_owned(command, inherit_fds=(), input="fixture", capture_output=True,
                                          text=True, timeout=5)
    assert result.returncode == 3 and result.stdout == "fixture" and result.stderr == ""
    with pytest.raises(subprocess.CalledProcessError) as captured:
        safe_subprocess.run_cli_owned(command, inherit_fds=(), input="fixture", capture_output=True,
                                      text=True, timeout=5, check=True)
    assert captured.value.returncode == 3 and captured.value.output == "fixture"
