"""Start, stop or restart the shared docker stack through Nightshift's root executor.

SummitFlow holds no docker rights: the stack is the root unit
``summitflow-stack.service`` and the typed ``unit.*`` actions drive it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import safe_subprocess

STACK_UNIT = "summitflow-stack.service"
ACTIONS = {"start": "unit.start", "stop": "unit.stop", "restart": "unit.restart"}
WAIT_SECONDS = 30


@dataclass(frozen=True)
class StackResult:
    success: bool
    message: str
    pending: bool = False
    approve_url: str | None = None


def stack_installed() -> bool:
    """False until the Nightshift root install exists; callers then keep the pre-install docker path."""
    return any(Path(base, STACK_UNIT).exists() for base in ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"))


def _nightshift() -> str:
    return shutil.which("nightshift") or str(Path.home() / ".local/bin/nightshift")


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return safe_subprocess.run([_nightshift(), *args], capture_output=True, text=True, timeout=timeout, check=False)


def _approve_link() -> str | None:
    """The owner-tap link waiting for the stack unit, if there is one."""
    try:
        rows = json.loads(_run(["pending", "--json"], 10).stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    ours = [row for row in rows if STACK_UNIT in str(row.get("title", ""))]
    return str((ours or rows or [{}])[0].get("url") or "") or None


def request_stack(action: Literal["start", "stop", "restart"], *, wait: int = WAIT_SECONDS) -> StackResult:
    """Ask Nightshift to run ``action`` on the stack unit; an owner tap comes back as a pending result."""
    try:
        done = _run(["request", ACTIONS[action], f"unit={STACK_UNIT}", "--reason", "recover",
                     "--agent", "summitflow", "--wait", str(wait)], wait + 15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return StackResult(False, f"Nightshift request failed: {exc}")
    text = done.stdout
    start = text.find("{")
    try:
        reply = json.JSONDecoder().raw_decode(text[start:])[0] if start >= 0 else {}
    except ValueError:
        reply = {}
    outcome = str(reply.get("outcome") or "")
    if outcome in {"applied", "noop"}:
        return StackResult(True, f"{action.capitalize()} of the docker stack applied")
    if outcome in {"", "pending"} and start >= 0:
        url = _approve_link()
        waiting = f"waiting for the owner's tap: {url}" if url else "still running; check back shortly"
        return StackResult(True, f"{action.capitalize()} of the docker stack requested, {waiting}", pending=True, approve_url=url)
    detail = str(reply.get("error") or outcome or text.strip() or done.stderr.strip() or "no answer")
    return StackResult(False, f"{action.capitalize()} of the docker stack not applied: {detail}")
