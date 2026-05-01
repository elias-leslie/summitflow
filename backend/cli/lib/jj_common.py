"""Shared Jujutsu primitives for st-owned VCS workflows."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

JJ_TIMEOUT_SECONDS = 300
JJ_GLOBAL_ARGS = [
    "--no-pager",
    "--config",
    'ui.editor="true"',
    "--config",
    'ui.paginate="never"',
    "--config",
    'ui.diff-editor=":builtin"',
]
CURRENT_REV_TEMPLATE = (
    'change_id.short() ++ "\\t" ++ commit_id.short() ++ "\\t" ++ '
    'if(empty, "empty", "nonempty") ++ "\\t" ++ '
    'if(conflict, "conflict", "clean") ++ "\\t" ++ '
    'description.first_line() ++ "\\n"'
)
LOG_TEMPLATE = (
    'change_id.short() ++ "\\t" ++ commit_id.short() ++ "\\t" ++ '
    'author.email() ++ "\\t" ++ committer.timestamp().format("%Y-%m-%d %H:%M:%S") ++ "\\t" ++ '
    'description.first_line() ++ "\\n"'
)
OP_LOG_TEMPLATE = 'id.short() ++ "\\t" ++ description.first_line() ++ "\\n"'
BOOKMARK_TEMPLATE = 'bookmarks ++ "\\n"'


class JJError(RuntimeError):
    """Raised when jj is unavailable or a jj command fails."""


@dataclass(frozen=True)
class JJRevisionInfo:
    change_id: str
    commit_id: str
    empty: bool
    conflict: bool
    description: str


@dataclass(frozen=True)
class JJRepoStatus:
    repo: str
    path: str
    branch: str
    colocated: bool
    state: str
    described: bool
    conflicted: bool
    unpublished: int
    change_id: str = "-"
    commit_id: str = "-"


def jj_binary() -> str:
    """Return the jj binary path or raise a clear error."""
    binary = shutil.which("jj")
    if not binary:
        raise JJError("jj is not installed or not on PATH")
    return binary


def run_jj(
    repo: Path,
    args: list[str],
    *,
    timeout: int = JJ_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run jj non-interactively in repo."""
    command = [jj_binary(), *JJ_GLOBAL_ARGS, *args]
    return subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def run_git(repo: Path, args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run git for compatibility checks around a colocated jj repo."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def current_git_repo() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise JJError("not inside a git repository")
    return Path(result.stdout.strip())


def is_colocated(repo: Path) -> bool:
    return (repo / ".jj").is_dir() and (repo / ".git").exists()


def require_success(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise JJError(f"{action} failed: {detail}")
