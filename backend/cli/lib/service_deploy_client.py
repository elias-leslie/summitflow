"""Runtime deployment routes: service-user sockets and typed Nightshift owner actions."""

from __future__ import annotations

import getpass
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path

from app.utils import safe_subprocess
from app.utils.agent_execution import run_as_agent, run_source_git

SOCKET_DIR = Path("/run/summitflow-deploy")
VERBS = ("deploy", "rollback", "stop", "status")
# The gate streams the command's output, then ends with one `[gate] exit <code>` line.
_EXIT = re.compile(r"\[gate\] exit (\d+)")


def delegated_user(runtime_user: str) -> str:
    """The delegated target; owner always uses approval, including owner callers."""
    if runtime_user == "owner":
        return "owner"
    return "" if not runtime_user or getpass.getuser() == runtime_user else runtime_user


def main_sha(checkout: Path, *, as_agent: bool = False) -> str:
    runner = run_as_agent if as_agent else run_source_git
    result = runner(
        ["git", "-C", str(checkout), "rev-parse", "--verify", "refs/heads/main^{commit}"],
        cwd=checkout, capture_output=True, text=True, check=False,
    )
    sha = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise OSError(f"{checkout} has no refs/heads/main commit to deploy")
    return sha


def send(user: str, project: str, sha: str, verb: str) -> int:
    """Send one request and stream the reply; return the gate's exit code (1 if it never said)."""
    if verb not in VERBS:
        raise ValueError(f"unknown deploy verb: {verb}")
    if user == "owner":
        return send_owner(project, sha, verb)
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


def send_owner(project: str, sha: str, verb: str) -> int:
    """Use Nightshift's typed action inbox; no owner deploy socket or local fallback.

    The request CLI prints its supported JSON response when --wait is supplied.
    A pending approval is not successful deployment evidence.
    """
    if verb not in VERBS:
        raise ValueError(f"unknown deploy verb: {verb}")
    executable = shutil.which("nightshift")
    if not executable:
        raise OSError("Nightshift owner action route is not installed")
    if verb in {"deploy", "rollback"}:
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("owner deployment requires a full commit id")
        if verb == "deploy":
            from .service_owner_artifact import initialize_owner_store

            initialize_owner_store(project)
        action = "owner.deploy"
        params = [f"project={project}", f"sha={sha}", f"operation={verb}"]
    elif verb == "status":
        action, params = "owner.status", [f"project={project}"]
    else:
        action, params = "owner.service", [f"project={project}", "operation=stop"]
    try:
        completed = safe_subprocess.run(
            [executable, "request", action, *params, "--reason", "diagnose" if verb == "status" else "deploy",
             "--agent", "summitflow", "--wait", "3600"],
            capture_output=True, text=True, check=False, timeout=3615,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("Nightshift owner action response timed out; completion is unknown") from exc
    # Preserve the public response (approval link/error/verification) without
    # treating CLI success or an approval itself as a completed mutation.
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n", flush=True)
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", flush=True)
    try:
        reply = json.JSONDecoder().raw_decode(completed.stdout.lstrip())[0]
    except (ValueError, TypeError):
        return 1
    return 0 if completed.returncode == 0 and isinstance(reply, dict) and reply.get("outcome") in {"applied", "noop", "no-op"} else 1
