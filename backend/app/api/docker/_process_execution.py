"""Subprocess runners for Docker and systemd commands."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .constants import (
    _COMMAND_TIMEOUT_SECONDS,
    _SYSTEMCTL_TIMEOUT_SECONDS,
    _USER_DBUS_ADDRESS,
    _USER_RUNTIME_DIR,
)

__all__ = [
    "_communicate_with_timeout",
    "_run_command",
    "_run_docker",
    "_run_journalctl_user",
    "_run_systemctl_user",
    "_systemctl_user_env",
]


async def _communicate_with_timeout(
    proc: asyncio.subprocess.Process,
    *,
    stdin_data: bytes | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_data), timeout=timeout)
    except TimeoutError:
        proc.kill()
        try:
            stdout, stderr = await proc.communicate()
        except Exception:
            stdout, stderr = b"", b""
        detail = f"Timed out after {timeout:.2f}s" if timeout is not None else "Timed out"
        return stdout.decode(), detail, 124
    return stdout.decode(), stderr.decode(), proc.returncode or 0


async def _run_docker(
    *args: str,
    stdin_data: bytes | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    """Run a docker command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin_data else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return await _communicate_with_timeout(proc, stdin_data=stdin_data, timeout=timeout)


async def _run_command(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = _COMMAND_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    """Run a shell command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return await _communicate_with_timeout(proc, timeout=timeout)


def _systemctl_user_env() -> dict[str, str]:
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = str(_USER_RUNTIME_DIR)
    env["DBUS_SESSION_BUS_ADDRESS"] = _USER_DBUS_ADDRESS
    return env


async def _run_systemctl_user(
    *args: str,
    timeout: float = _SYSTEMCTL_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    return await _run_command(
        "systemctl",
        "--user",
        *args,
        env=_systemctl_user_env(),
        timeout=timeout,
    )


async def _run_journalctl_user(*args: str) -> tuple[str, str, int]:
    return await _run_command(
        "journalctl",
        "--user",
        *args,
        env=_systemctl_user_env(),
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
