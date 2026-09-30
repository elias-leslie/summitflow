"""Git utility operations."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ...logging_config import get_logger
from ...utils import safe_subprocess

logger = get_logger(__name__)


def network_repository_identity(url: str) -> tuple[str, int | None, str] | None:
    """Compare existing SSH/HTTPS repository routes without retaining secrets."""
    if not url or any(character.isspace() for character in url) or "\0" in url:
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme in {"https", "ssh"} and parsed.hostname:
            if parsed.query or parsed.fragment:
                return None
            host, path, port = parsed.hostname, parsed.path, parsed.port
            if port in {443 if parsed.scheme == "https" else 22}:
                port = None
        else:
            scp = re.fullmatch(r"(?:[A-Za-z0-9_.-]+@)?([^/:]+):(.+)", url)
            if not scp or "://" in url or "::" in url or parsed.scheme in {"file", "http", "ext"}:
                return None
            host, path, port = scp[1], scp[2], None
        host = host.lower().rstrip(".")
        if not host or host.startswith("-"):
            return None
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
            return None
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if address is not None and (address.is_loopback or address.is_unspecified):
            return None
        path = path.strip("/")
        if not path:
            return None
        return host, port, path.removesuffix(".git")
    except ValueError:
        return None


def push_captured_head_to_upstream(
    project_path: str | Path,
    head: str,
    upstream_ref: str,
    push_url: str,
    *,
    ssh_command: str = "ssh",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Publish one validated captured commit; return only sanitized outcomes.

    The caller verifies the current branch's existing upstream and transport.
    A captured URL avoids redirection through a concurrently edited remote name.
    GNU timeout bounds Git and its SSH/credential/hook process group together.
    No raw URL, command output or exception is returned or logged.
    """
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) or upstream_ref not in {"refs/heads/main", "refs/heads/master"} or network_repository_identity(push_url) is None:
        return {"status": "failed", "reason": "invalid_push_request", "attempted": False}
    timeout = shutil.which("timeout")
    if timeout is None:
        return {"status": "failed", "reason": "timeout_tool_unavailable", "attempted": False}
    if not 1 <= timeout_seconds <= 300:
        return {"status": "failed", "reason": "invalid_push_timeout", "attempted": False}
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({
        "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never",
        "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "/bin/false",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_SSH_COMMAND": ssh_command + " -o BatchMode=yes -o ConnectTimeout=10",
    })
    command = [
        timeout, "--signal=TERM", "--kill-after=5s", f"{timeout_seconds}s",
        "git", "-C", str(project_path), "-c", "push.followTags=false",
        "push", "--porcelain", "--no-follow-tags", "--recurse-submodules=no",
        "--", push_url, f"{head}:{upstream_ref}",
    ]
    try:
        result = safe_subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=environment, timeout=timeout_seconds + 10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "reason": "push_timeout", "attempted": True}
    except OSError:
        return {"status": "failed", "reason": "push_transport_unavailable", "attempted": True}
    if result.returncode in {124, 137}:
        return {"status": "failed", "reason": "push_timeout", "attempted": True}
    if result.returncode != 0:
        return {"status": "failed", "reason": "push_failed", "attempted": True}
    return {"status": "published", "reason": "captured_head_published", "attempted": True}


def push_branch(
    branch_name: str,
    project_path: str | Path,
    set_upstream: bool = True,
) -> bool:
    """Push a branch to remote origin.

    Args:
        branch_name: Name of the branch to push
        project_path: Path to the git repository
        set_upstream: Whether to set upstream tracking (default True)

    Returns:
        True if successful

    Raises:
        RuntimeError: If push fails
    """
    project_path = Path(project_path)

    cmd = ["git", "push"]
    if set_upstream:
        cmd.extend(["-u", "origin", branch_name])
    else:
        cmd.extend(["origin", branch_name])

    result = safe_subprocess.run(
        ["git", "-C", str(project_path), *cmd[1:]],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("push_failed", branch=branch_name, error=result.stderr)
        raise RuntimeError(f"Failed to push branch: {result.stderr}")

    logger.info("branch_pushed", branch=branch_name)
    return True


def revert_to(repo_path: Path | str, sha: str) -> bool:
    """Hard reset repository to a specific commit.

    WARNING: This is destructive! All uncommitted changes will be lost.

    Args:
        repo_path: Path to the git repository
        sha: Commit SHA to reset to

    Returns:
        True if successful

    Raises:
        RuntimeError: If reset fails
    """
    repo_path = Path(repo_path)

    result = safe_subprocess.run(
        ["git", "-C", str(repo_path), "reset", "--hard", sha],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("revert_failed", sha=sha[:8], error=result.stderr)
        raise RuntimeError(f"Failed to revert to {sha}: {result.stderr}")

    logger.info("reverted", sha=sha[:8])
    return True


def get_head_sha(repo_path: str | Path) -> str:
    """Get the current HEAD commit SHA.

    Args:
        repo_path: Path to git repository

    Returns:
        Full commit SHA
    """
    repo_path = Path(repo_path)

    result = safe_subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get HEAD SHA: {result.stderr}")

    return result.stdout.strip()


def get_blob_shas(repo_path: str | Path, paths: list[str]) -> dict[str, str]:
    """Get blob SHAs for specific files (for rebase-resistant tracking).

    Args:
        repo_path: Path to git repository
        paths: List of file paths to get SHAs for

    Returns:
        Dict mapping file paths to their blob SHAs
    """
    repo_path = Path(repo_path)
    result: dict[str, str] = {}

    for path in paths:
        try:
            proc = safe_subprocess.run(
                ["git", "-C", str(repo_path), "ls-files", "-s", path],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                # Output format: <mode> <sha> <stage>\t<file>
                parts = proc.stdout.split()
                if len(parts) >= 2:
                    result[path] = parts[1]
        except subprocess.SubprocessError:
            pass  # Skip files that don't exist or error

    return result
