"""Control the existing root-owned Docker stack using routine noninteractive sudo."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import safe_subprocess

STACK_UNIT = "summitflow-stack.service"
WAIT_SECONDS = 30


@dataclass(frozen=True)
class StackResult:
    success: bool
    message: str


def stack_installed() -> bool:
    """Use the system stack unit when installed; retain compose before installation."""
    return any(Path(base, STACK_UNIT).exists() for base in ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"))


def request_stack(action: Literal["start", "stop", "restart"], *, wait: int = WAIT_SECONDS) -> StackResult:
    """Keep the existing caller contract while using the owner's routine sudo authority."""
    try:
        done = safe_subprocess.run(
            ["sudo", "-n", "systemctl", "--no-ask-password", action, STACK_UNIT],
            capture_output=True, text=True, timeout=wait + 15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return StackResult(False, f"Docker stack control failed: {exc}")
    if done.returncode == 0:
        return StackResult(True, f"{action.capitalize()} of the docker stack applied")
    detail = done.stderr.strip() or done.stdout.strip() or f"systemctl returned {done.returncode}"
    return StackResult(False, f"{action.capitalize()} of the docker stack not applied: {detail}")
