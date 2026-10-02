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


def test_duplex_spawn_failure_closes_all_pipe_descriptors(monkeypatch) -> None:
    import os

    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(FileNotFoundError):
        safe_subprocess.spawn_duplex(["/does/not/exist"])
    assert len(os.listdir("/proc/self/fd")) == before
