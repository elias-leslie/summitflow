"""Client for the per-user deploy sockets: projects with ``runtime.runtime_user`` deploy through the gate."""

from __future__ import annotations

import getpass
import json
import re
import socket
from pathlib import Path

from app.utils.agent_execution import run_source_git

SOCKET_DIR = Path("/run/summitflow-deploy")
VERBS = ("deploy", "rollback", "stop", "status")
# The gate streams the command's output, then ends with one `[gate] exit <code>` line.
_EXIT = re.compile(r"\[gate\] exit (\d+)")


def delegated_user(runtime_user: str) -> str:
    """The socket to use, or "" when this process already is the runtime user."""
    return "" if not runtime_user or getpass.getuser() == runtime_user else runtime_user


def main_sha(checkout: Path) -> str:
    result = run_source_git(["git", "-C", str(checkout), "rev-parse", "--verify", "refs/heads/main^{commit}"],
                            capture_output=True, text=True, check=False)
    sha = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise OSError(f"{checkout} has no refs/heads/main commit to deploy")
    return sha


def send(user: str, project: str, sha: str, verb: str) -> int:
    """Send one request and stream the reply; return the gate's exit code (1 if it never said)."""
    if verb not in VERBS:
        raise ValueError(f"unknown deploy verb: {verb}")
    request = json.dumps({"project": project, "sha": sha, "verb": verb}) + "\n"
    code = 1
    with socket.socket(socket.AF_UNIX) as sock:
        sock.connect(str(SOCKET_DIR / f"{user}.sock"))
        sock.sendall(request.encode())
        with sock.makefile("r", encoding="utf-8", errors="replace") as reply:
            for line in reply:
                if match := _EXIT.fullmatch(line.strip()):
                    code = int(match.group(1))
                else:
                    print(line, end="", flush=True)
    return code
