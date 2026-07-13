"""Helper utilities for command_guard.py — parsing, git argument extraction, and subcommand decisions."""

from __future__ import annotations

import contextlib
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..utils import safe_subprocess
from ..utils._git_core import get_managed_repos

_SHELL_SEPARATORS = frozenset({";", "&&", "||", "|"})
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_COMMAND_WRAPPERS = frozenset({"command", "builtin", "nohup"})
_OPTION_WRAPPERS = frozenset({"nice", "stdbuf", "timeout"})
_ENV_OPTIONS_WITH_VALUE = frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string", "--argv0"})
_SUDO_OPTIONS_WITH_VALUE = frozenset({
    "-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt",
    "-C", "--close-from", "-T", "--command-timeout", "-R", "--chroot",
    "-D", "--chdir",
})
_GIT_REPO_CHECK = ["git", "rev-parse", "--is-inside-work-tree"]

GIT_ABORT_ACTIONS = frozenset({"--abort", "--continue", "--quit", "--skip"})
SHELL_EXECUTABLES = frozenset({"bash", "sh", "zsh", "ksh"})
BASH_INTERCEPT_WORDS: tuple[str, ...] = (
    "git", "jj", "python", "python3", "pytest", "mypy", "ty", "ruff", "biome",
    "npx", "pnpm", "npm", "vitest", "sqlfluff", "squawk",
    "docker", "env", "nohup", "nice", "stdbuf", "timeout", "sudo", "Xorg", "Xvfb", "bash", "sh",
    "st", "systemctl", "pkill", "killall", "uvicorn", "gunicorn", "next", "psql",
    "rm", "rmdir", "find",
)
DANGEROUS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^rm\s+-[^\n]*r[^\n]*\s+(/\*?|\\\*)($|\s)"), "BLOCKED:rm -r /:Recursive root deletion is never allowed."),
    (re.compile(r"^mkfs(\.\S+)?(\s|$)"), "BLOCKED:mkfs:Formatting filesystems is never allowed."),
    (re.compile(r"^dd\b.*\bif=/dev/zero\b"), "BLOCKED:dd if=/dev/zero:Raw disk overwrite is never allowed."),
    (re.compile(r"^systemctl\s+(stop|disable)\b"), "BLOCKED:systemctl stop/disable:Do not stop or disable services directly."),
)
# Type alias for the path-conflict checker callback
PathConflictFn = Callable[[Sequence[str], str], "CommandGuardDecision | None"]

@dataclass(frozen=True)
class CommandGuardDecision:
    """Result of evaluating one shell command."""

    blocked: bool
    code: str | None
    message: str | None
    source: str | None
    command: str

    def to_dict(self) -> dict[str, object]:
        return {
            "blocked": self.blocked,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "command": self.command,
        }

def normalize_segment(segment: Sequence[str]) -> str:
    return shlex.join(list(segment))

def split_shell_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return [[command]]
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments

def unwrap_segment_with_privilege(segment: Sequence[str]) -> tuple[list[str], bool]:
    """Remove execution wrappers and report whether sudo elevated the command."""
    tokens = list(segment)
    privileged = False
    idx = next((i for i, t in enumerate(tokens) if not _ASSIGNMENT_RE.match(t)), len(tokens))
    tokens = tokens[idx:]
    while tokens:
        lead = Path(tokens[0]).name
        if lead == "env":
            i = 1
            while i < len(tokens):
                t = tokens[i]
                if t == "--":
                    i += 1
                    break
                if t in _ENV_OPTIONS_WITH_VALUE and i + 1 < len(tokens):
                    i += 2
                elif t.startswith("-") or _ASSIGNMENT_RE.match(t):
                    i += 1
                else:
                    break
            tokens = tokens[i:]
        elif lead == "sudo":
            privileged = True
            i = 1
            while i < len(tokens):
                t = tokens[i]
                if t == "--":
                    i += 1
                    break
                if t in _SUDO_OPTIONS_WITH_VALUE and i + 1 < len(tokens):
                    i += 2
                elif t.startswith("-") or _ASSIGNMENT_RE.match(t):
                    i += 1
                else:
                    break
            tokens = tokens[i:]
        elif lead in _COMMAND_WRAPPERS:
            tokens = tokens[1:]
        elif lead in _OPTION_WRAPPERS:
            i = 1
            while i < len(tokens) and tokens[i].startswith("-"):
                opt = tokens[i]
                i += 1
                if opt in {"-n", "--adjustment", "-s", "--signal", "-k"} and i < len(tokens):
                    i += 1
            tokens = tokens[i:]
        else:
            break
    return tokens, privileged


def unwrap_segment(segment: Sequence[str]) -> list[str]:
    tokens, _privileged = unwrap_segment_with_privilege(segment)
    return tokens

def git_has_flag(args: Sequence[str], *flags: str) -> bool:
    return any(
        arg in flags or any(arg.startswith(f"{flag}=") for flag in flags)
        for arg in args
    )

def shell_exec_args(args: Sequence[str]) -> str | None:
    for idx, arg in enumerate(args):
        if arg == "-c" and idx + 1 < len(args):
            return args[idx + 1]
        if arg.startswith("-") and "c" in arg[1:] and idx + 1 < len(args):
            return args[idx + 1]
    return None

def git_paths_after_double_dash(args: Sequence[str]) -> list[str]:
    args_list = list(args)
    if "--" not in args_list:
        return []
    idx = args_list.index("--")
    return [token for token in args_list[idx + 1:] if not token.startswith("-")]

def strip_git_option_values(args: Sequence[str], *, value_flags: set[str]) -> list[str]:
    stripped: list[str] = []
    idx = 0
    while idx < len(args):
        token = args[idx]
        if token in value_flags:
            idx += 2
        elif any(token.startswith(f"{flag}=") for flag in value_flags):
            idx += 1
        else:
            stripped.append(token)
            idx += 1
    return stripped

def git_restore_paths(args: Sequence[str]) -> tuple[list[str], bool]:
    restore_include_full_checkout_flag = "--" + "wor" + "ktree"
    if git_has_flag(args, "--staged") and not git_has_flag(args, restore_include_full_checkout_flag):
        return [], True
    cleaned = strip_git_option_values(args, value_flags={"--source", "--pathspec-from-file"})
    explicit = git_paths_after_double_dash(cleaned)
    if explicit:
        return explicit, False
    return [token for token in cleaned if not token.startswith("-")], False

def git_revert_paths(repo_root: Path, args: Sequence[str], error_class: type[Exception]) -> list[str]:
    cleaned = strip_git_option_values(
        args, value_flags={"-m", "--mainline", "-X", "--strategy-option", "--strategy"},
    )
    revisions = [arg for arg in cleaned if arg and not arg.startswith("-")]
    if not revisions:
        return []
    try:
        result = safe_subprocess.run(
            ["git", "-C", str(repo_root), "show", "--format=", "--name-only", "--no-renames", *revisions],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise error_class(f"Failed to inspect git revert paths for {' '.join(revisions)}: {exc}") from exc
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def force_pushes_shared_main(args: Sequence[str]) -> bool:
    if not git_has_flag(args, "-f", "--force"):
        return False
    return any(
        arg in {"main", "master", "origin/main", "origin/master"}
        or arg.endswith(":main") or arg.endswith(":master")
        for arg in args
    )

def normalize_repo_paths(repo_root: Path, raw_paths: Sequence[str]) -> list[str]:
    result: list[str] = []
    for raw in raw_paths:
        path = raw.strip()
        if not path:
            continue
        target = Path(path).expanduser()
        if not target.is_absolute():
            result.append(path)
            continue
        with contextlib.suppress(OSError, ValueError):
            result.append(target.resolve().relative_to(repo_root).as_posix())
    return result

def is_inside_git_repo(path: Path) -> bool:
    try:
        result = safe_subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"

def repo_root(cwd: Path) -> Path | None:
    try:
        result = safe_subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def is_managed_repo_root(root: Path | None) -> bool:
    """Return True when root is a managed repo path; fail closed on lookup errors."""
    if root is None:
        return False
    try:
        resolved_root = root.resolve()
    except OSError:
        resolved_root = root
    try:
        return any(repo == resolved_root for repo in get_managed_repos())
    except Exception:
        return True

def explicit_repo_target(tokens: Sequence[str], cwd: Path) -> bool:
    if not tokens:
        return False
    command = tokens[0]
    if command in {"rm", "rmdir"}:
        target_token = next((t for t in tokens[1:] if not t.startswith("-")), None)
        if not target_token:
            return False
        target = Path(target_token).expanduser()
        if not target.is_absolute():
            target = (cwd / target).resolve()
        check = target.parent if not target.exists() else target
        return is_inside_git_repo(check)
    if command == "find":
        for token in tokens[1:]:
            if token == "-delete":
                break
            if token.startswith("-"):
                continue
            target = Path(token).expanduser()
            if not target.is_absolute():
                target = (cwd / target).resolve()
            if is_inside_git_repo(target):
                return True
    return False

def git_checkout_decision(
    args: list[str], segment_text: str, root: Path | None, check_fn: PathConflictFn,
) -> CommandGuardDecision | None:
    msg = "BLOCKED:git checkout .:Discards all uncommitted changes at once."
    paths = git_paths_after_double_dash(args)
    if args[:1] == ["."] or args[:2] == ["--", "."] or "." in paths:
        if is_managed_repo_root(root):
            return CommandGuardDecision(blocked=True, code="git_checkout_all", message=msg, source="git", command=segment_text)
        return None
    return check_fn(paths, segment_text) if paths else None

def git_restore_decision(
    args: list[str], segment_text: str, root: Path | None, check_fn: PathConflictFn,
) -> CommandGuardDecision | None:
    msg = "BLOCKED:git restore .:Discards all uncommitted changes at once."
    if args[:1] == ["."]:
        if is_managed_repo_root(root):
            return CommandGuardDecision(blocked=True, code="git_restore_all", message=msg, source="git", command=segment_text)
        return None
    paths, staging_only = git_restore_paths(args)
    if staging_only:
        return None
    if "." in paths:
        if is_managed_repo_root(root):
            return CommandGuardDecision(blocked=True, code="git_restore_all", message=msg, source="git", command=segment_text)
        return None
    return check_fn(paths, segment_text)

def git_revert_decision(
    args: list[str],
    segment_text: str,
    root: Path | None,
    check_fn: PathConflictFn,
    error_class: type[Exception],
) -> CommandGuardDecision | None:
    if any(flag in args for flag in GIT_ABORT_ACTIONS) or not root:
        return None
    paths = git_revert_paths(root, args, error_class)
    return check_fn(paths, segment_text)
