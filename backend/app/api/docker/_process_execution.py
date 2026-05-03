"""Subprocess runners for Docker and systemd commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ...utils import safe_subprocess
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
    proc: object,
    *,
    stdin_data: bytes | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    """Compatibility shim; new callers use safe_subprocess directly."""
    _ = (proc, stdin_data)
    detail = f"Timed out after {timeout:.2f}s" if timeout is not None else "Timed out"
    return "", detail, 124


async def _run_safe_command(
    args: tuple[str, ...],
    *,
    stdin_data: bytes | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    try:
        result = await safe_subprocess.run_async(
            list(args),
            cwd=cwd,
            env=env,
            input=stdin_data,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        detail = f"Timed out after {timeout:.2f}s" if timeout is not None else "Timed out"
        return "", detail, 124
    except OSError as exc:
        return "", str(exc), 127
    stdout = result.stdout.decode(errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout or "")
    stderr = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
    return stdout, stderr, result.returncode


async def _run_docker(
    *args: str,
    stdin_data: bytes | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    """Run a docker command asynchronously."""
    return await _run_safe_command(args, stdin_data=stdin_data, timeout=timeout)


async def _run_command(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = _COMMAND_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    """Run a shell command asynchronously."""
    return await _run_safe_command(args, cwd=cwd, env=env, timeout=timeout)


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
