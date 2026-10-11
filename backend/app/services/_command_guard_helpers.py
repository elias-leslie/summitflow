"""Helper utilities for command_guard.py — parsing, git argument extraction, and subcommand decisions."""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The publication hook imports this module with a stdlib-only interpreter (see
# scripts/lib/command-guard). Backend utilities load structlog/pydantic, so they
# are imported only by the functions that need them.


class _LazySafeSubprocess:
    @staticmethod
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        from ..utils import safe_subprocess as module

        return module.run(*args, **kwargs)


safe_subprocess = _LazySafeSubprocess()


def get_managed_repos() -> list[Path]:
    from ..utils._git_core import get_managed_repos as managed_repos

    return managed_repos()

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
    "git", "jj", "gh", "python", "python3", "pytest", "mypy", "ty", "ruff", "biome",
    "npx", "pnpm", "npm", "vitest", "sqlfluff", "squawk",
    "docker", "env", "nohup", "nice", "stdbuf", "timeout", "sudo",
    "X", "Xorg", "Xorg.bin", "Xvfb", "xinit", "startx", "bash", "sh",
    "st", "systemctl", "pkill", "killall", "uvicorn", "gunicorn", "next", "psql",
    "rm", "rmdir", "find",
)
DANGEROUS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^rm\s+-[^\n]*r[^\n]*\s+(/\*?|\\\*)($|\s)"), "BLOCKED:rm -r /:Recursive root deletion is never allowed."),
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
        lead = Path(tokens[0]).name.casefold()
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
                if opt in {"-n", "--adjustment", "-s", "--signal", "-k", "--kill-after"} and i < len(tokens):
                    i += 1
            if lead == "timeout" and i < len(tokens):
                i += 1  # timeout DURATION COMMAND: skip the positional duration
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


# --- Irreversible-command policy -------------------------------------------
# Shared by the live PreToolUse hook (publication_hook -> _publication_guard)
# and evaluate_shell_command. Pure string/path logic: no subprocess, network,
# or filesystem access, so it stays stdlib-only and fast inside the hook.

_GIT_GLOBAL_OPTIONS_WITH_VALUE = frozenset({
    "-c", "--config-env", "--exec-path", "--git-dir", "--namespace", "--super-prefix", "--work-tree",
})
# Throwaway locations: whole-tree discards there cannot hit another agent's work.
DISPOSABLE_ROOTS: tuple[str, ...] = ("/tmp", "/var/tmp", "/dev/shm", "/srv/scratch")
# Mounted storage (backup drives, archives): never a recursive-delete target.
_MOUNTED_STORAGE_ROOTS: tuple[str, ...] = ("/mnt", "/media")
# Proxmox VM images and cluster config (reached over ssh): never a recursive-delete target.
_PROXMOX_DATA_ROOTS: tuple[str, ...] = ("/var/lib/vz", "/etc/pve")
_BROAD_PATHSPECS = frozenset({".", "./", ":/", ":/*", ":(top)", "*"})
_STASH_READ_OR_APPLY = frozenset({"list", "show", "apply", "pop", "branch", "create", "store"})


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def git_invocation(tokens: Sequence[str], cwd: str) -> tuple[str, list[str], str] | None:
    """Return (subcommand, args, effective cwd) for an unwrapped ``git`` argv."""
    if len(tokens) < 2 or Path(tokens[0]).name != "git":
        return None
    index = 1
    git_cwd = cwd
    while index < len(tokens):
        token = tokens[index]
        if token == "-C" and index + 1 < len(tokens):
            git_cwd = os.path.normpath(os.path.join(git_cwd, os.path.expanduser(tokens[index + 1])))
            index += 2
        elif token.startswith("-C") and token != "-C":
            git_cwd = os.path.normpath(os.path.join(git_cwd, os.path.expanduser(token[2:])))
            index += 1
        elif token in _GIT_GLOBAL_OPTIONS_WITH_VALUE and index + 1 < len(tokens):
            index += 2
        elif token.startswith("-"):
            index += 1
        else:
            return token, list(tokens[index + 1:]), git_cwd
    return None


def _short_flags(args: Sequence[str]) -> set[str]:
    flags: set[str] = set()
    for arg in args:
        if arg == "--":
            break
        if arg.startswith("-") and not arg.startswith("--"):
            flags.update(arg[1:])
    return flags


def _git_blocked(code: str, message: str, command: str) -> CommandGuardDecision:
    return CommandGuardDecision(blocked=True, code=code, message=message, source="git", command=command)


def irreversible_git_decision(
    subcommand: str, args: Sequence[str], segment_text: str, *, shared_checkout: bool,
) -> CommandGuardDecision | None:
    """Deny git commands that destroy uncommitted or shared work without recovery."""
    if subcommand == "push" and force_pushes_shared_main(args):
        return _git_blocked(
            "git_force_push_main",
            "BLOCKED:git push --force main:Force push to main/master destroys shared history; publish with 'st vcs publish'.",
            segment_text,
        )
    if not shared_checkout:
        return None
    if subcommand == "reset" and git_has_flag(args, "--hard"):
        return _git_blocked(
            "git_reset_hard",
            "BLOCKED:git reset --hard:Discards every agent's uncommitted work in this shared checkout; "
            "restore only your files with 'git restore -- <path>' or checkpoint with 'st commit --paths <path>'.",
            segment_text,
        )
    if subcommand == "clean":
        flags = _short_flags(args)
        forced = "f" in flags or git_has_flag(args, "--force")
        dry_run = "n" in flags or git_has_flag(args, "--dry-run")
        if forced and not dry_run:
            return _git_blocked(
                "git_clean_fd",
                "BLOCKED:git clean:Permanently deletes untracked files other agents may own; "
                "remove your own files by explicit path (rm <path>), preview with 'git clean -n'.",
                segment_text,
            )
    if subcommand == "checkout":
        paths = git_paths_after_double_dash(args)
        if args[:1] == ["."] or any(path in _BROAD_PATHSPECS for path in paths):
            return _git_blocked(
                "git_checkout_all",
                "BLOCKED:git checkout .:Discards every agent's uncommitted changes in this shared checkout; "
                "name your own files: 'git checkout -- <path>'.",
                segment_text,
            )
    if subcommand == "restore":
        paths, staging_only = git_restore_paths(args)
        if not staging_only and any(path in _BROAD_PATHSPECS for path in paths):
            return _git_blocked(
                "git_restore_all",
                "BLOCKED:git restore .:Discards every agent's uncommitted changes in this shared checkout; "
                "name your own files: 'git restore -- <path>'.",
                segment_text,
            )
    if subcommand == "stash":
        action = args[0] if args and not args[0].startswith("-") else "push"
        if action in {"drop", "clear"}:
            return _git_blocked(
                "git_stash_drop",
                "BLOCKED:git stash drop/clear:Permanently deletes stashed work; leave stashes in place "
                "and inspect them with 'git stash list' / 'git stash show'.",
                segment_text,
            )
        if action not in _STASH_READ_OR_APPLY:
            return _git_blocked(
                "git_stash",
                "BLOCKED:git stash:Sweeps other agents' uncommitted changes out of this shared checkout; "
                "checkpoint your own files with 'st commit --paths <path>' instead.",
                segment_text,
            )
    return None


def _deletion_target(token: str, cwd: str) -> str | None:
    """Normalize an rm operand to the directory it destroys; None when unknowable."""
    home = os.path.expanduser("~")
    for prefix in ("${HOME}", "$HOME"):
        if token == prefix or token.startswith(prefix + "/"):
            token = home + token[len(prefix):]
    token = os.path.expanduser(token)
    if "$" in token or "`" in token:
        return None
    # "dir/*" and "dir/.*" destroy dir's contents: judge dir itself.
    while token in {"*", ".*"} or token.endswith(("/*", "/.*")):
        token = token.rsplit("/", 1)[0] if "/" in token else "."
        token = token or "/"
    return os.path.normpath(os.path.join(cwd, token))


def protected_deletion_root(target: str) -> bool:
    """True when recursively deleting ``target`` would destroy a protected root."""
    home = os.path.normpath(os.path.expanduser("~"))
    if target.count("/") <= 1 or target == home:  # "/", "/etc", "/home", "/srv", ...
        return True
    # /home/<user>, /srv/<area> (workspaces, models, scratch), and each project root.
    if os.path.dirname(target) in {"/home", "/srv", "/srv/workspaces/projects"}:
        return True
    if target == "/srv/workspaces/projects":
        return True
    return any(_under(target, root) for root in (*_MOUNTED_STORAGE_ROOTS, *_PROXMOX_DATA_ROOTS))


def irreversible_rm_decision(tokens: Sequence[str], cwd: str) -> CommandGuardDecision | None:
    """Deny recursive ``rm`` of a protected root (/, home, /srv/..., project roots, mounts)."""
    if not tokens or Path(tokens[0]).name != "rm":
        return None
    recursive = False
    operands: list[str] = []
    options_done = False
    for token in tokens[1:]:
        if not options_done and token == "--":
            options_done = True
        elif not options_done and token.startswith("--"):
            recursive = recursive or token == "--recursive"
        elif not options_done and token.startswith("-") and token != "-":
            recursive = recursive or bool(set(token[1:]) & {"r", "R"})
        else:
            operands.append(token)
    if not recursive:
        return None
    for operand in operands:
        target = _deletion_target(operand, cwd)
        if target and protected_deletion_root(target):
            return CommandGuardDecision(
                blocked=True,
                code="rm_protected_root",
                message=(
                    f"BLOCKED:rm -r {target}:Recursive delete of a protected root (home, /srv, workspace or "
                    "project root, mounted storage) is irreversible; delete the specific subpaths you own instead."
                ),
                source="dangerous",
                command=normalize_segment(tokens),
            )
    return None


# --- Host-level irreversible commands: disks, snapshots, backups, Proxmox ----
# Accident guard only: each rule fires on the destructive form and leaves
# listing, dry-run, and image-file/loop-device work alone.

_DISK_ADVICE = (
    "destroys every byte on a real disk and agents never run it; practice on an image file or "
    "loop device under /srv/scratch, or ask the owner to run it."
)
_HARMLESS_DEVICES = frozenset({
    "/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom",
    "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/tty",
})
_PARTED_WRITES = frozenset({
    "mklabel", "mktable", "mkpart", "mkpartfs", "mkfs", "rm", "resize", "resizepart",
    "rescue", "name", "set", "toggle", "disk_set", "disk_toggle", "type", "move", "cp",
})
_SGDISK_READ_ONLY = frozenset({
    "-p", "--print", "-i", "--info", "-v", "--verify", "-O", "--print-mbr", "-b", "--backup",
    "-L", "--list-types", "-P", "--pretend", "-V", "--version", "-?", "--help", "-a", "--set-alignment",
})
_PARTITIONER_READ_ONLY: dict[str, frozenset[str]] = {
    "fdisk": frozenset({"-l", "--list", "-x", "--list-details"}),
    "sfdisk": frozenset({
        "-l", "--list", "-d", "--dump", "-J", "--json", "-s", "--show-size", "-V", "--verify",
        "-g", "--show-geometry", "-F", "--list-free", "-n", "--no-act",
    }),
    "gdisk": frozenset({"-l"}),
    "cfdisk": frozenset(),
}
_CRYPTSETUP_DESTRUCTIVE = frozenset({"luksformat", "erase", "lukserase", "lukskillslot"})
_FORMATTERS = frozenset({"mke2fs", "mkswap", "mkdosfs", "mkntfs", "mkexfatfs"})
_SNAPSHOT_STORE = "/mnt/summitflow-native"
_RESTIC_OPTIONS_WITH_VALUE = frozenset({
    "-r", "--repo", "--repository-file", "-p", "--password-file", "--password-command",
    "--cacert", "--cache-dir", "-o", "--option", "--limit-upload", "--limit-download",
    "--tls-client-cert", "--pack-size", "--compression", "--key-hint", "--retry-lock",
    "--stuck-request-timeout", "--http-user-agent",
})
_RCLONE_DESTRUCTIVE = frozenset({"delete", "purge", "deletefile", "cleanup", "rmdirs", "rmdir"})
_RCLONE_REMOTE = re.compile(r"^[A-Za-z0-9_][\w. -]*:")
_FIND_GLOBAL_OPTIONS = frozenset({"-H", "-L", "-P"})
_FIND_SELECTIVE = frozenset({
    "-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex",
    "-lname", "-ilname", "-empty", "-samefile", "-inum",
})
_DELETING_EXECUTABLES = frozenset({"rm", "rmdir", "unlink", "shred"})
_SSH_OPTIONS_WITH_VALUE = frozenset("BbcDEeFIiJLlmOoPpQRSWw")


def _system_blocked(label: str, reason: str, tokens: Sequence[str]) -> CommandGuardDecision:
    code = "irreversible_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return CommandGuardDecision(
        blocked=True, code=code, message=f"BLOCKED:{label}:{reason}",
        source="dangerous", command=normalize_segment(tokens),
    )


def _real_device(token: str) -> bool:
    """True for a /dev block-device path (or an unresolved $VAR that may be one); loop devices are scratch."""
    value = token.split("=", 1)[1] if token.startswith(("of=", "if=")) else token
    if "$" in value or "`" in value:
        return True
    if not value.startswith("/dev/"):
        return False
    path = os.path.normpath(value)
    return (
        path not in _HARMLESS_DEVICES
        and not path.startswith(("/dev/fd/", "/dev/shm/", "/dev/pts/", "/dev/loop"))
    )


def _device_operands(args: Sequence[str]) -> bool:
    return any(not arg.startswith("-") and _real_device(arg) for arg in args)


def _positionals(args: Sequence[str], value_options: frozenset[str] = frozenset()) -> list[str]:
    result: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in value_options:
            skip = True
        elif not arg.startswith("-"):
            result.append(arg)
    return result


def _disk_decision(name: str, tokens: Sequence[str]) -> CommandGuardDecision | None:
    args = tokens[1:]
    if name.startswith("mkfs") or name in _FORMATTERS or name == "blkdiscard":
        if _device_operands(args):
            return _system_blocked(name, f"Formatting or discarding a device {_DISK_ADVICE}", tokens)
    elif name == "wipefs":
        flags = _short_flags(args)
        erasing = bool(flags & {"a", "o"}) or git_has_flag(args, "--all", "--offset")
        dry_run = "n" in flags or git_has_flag(args, "--no-act")
        if erasing and not dry_run and _device_operands(args):
            return _system_blocked("wipefs", f"Erasing filesystem signatures {_DISK_ADVICE} List with plain 'wipefs <dev>'.", tokens)
    elif name == "dd":
        if any(arg.startswith("of=") and _real_device(arg) for arg in args):
            return _system_blocked("dd of=/dev", f"Writing raw data to a device {_DISK_ADVICE} Write to a regular file instead.", tokens)
    elif name == "parted":
        if _device_operands(args) and any(arg.lower() in _PARTED_WRITES for arg in args):
            return _system_blocked("parted", f"Changing a partition table {_DISK_ADVICE} Inspect with 'parted -l' or 'parted <dev> print'.", tokens)
    elif name == "sgdisk":
        options = [arg.split("=", 1)[0] for arg in args if arg.startswith("-")]
        writes = [opt for opt in options if (opt if opt.startswith("--") else opt[:2]) not in _SGDISK_READ_ONLY]
        if writes and "-P" not in options and "--pretend" not in options and _device_operands(args):
            return _system_blocked("sgdisk", f"Changing a GPT {_DISK_ADVICE} Inspect with 'sgdisk -p <dev>'.", tokens)
    elif name in _PARTITIONER_READ_ONLY:
        read_only = _PARTITIONER_READ_ONLY[name]
        if not any(arg.split("=", 1)[0] in read_only for arg in args) and _device_operands(args):
            return _system_blocked(name, f"Repartitioning a disk {_DISK_ADVICE} Inspect with 'lsblk' or 'fdisk -l'.", tokens)
    elif name == "cryptsetup" and any(arg.lower() in _CRYPTSETUP_DESTRUCTIVE for arg in args) and _device_operands(args):
        return _system_blocked("cryptsetup", f"Formatting or erasing a LUKS header makes the data unrecoverable; it {_DISK_ADVICE}", tokens)
    return None


def _snapshot_target(raw: str, cwd: str) -> bool:
    target = _deletion_target(raw, cwd)
    text = (target or raw).lower()
    parts = text.split("/")
    return (
        (target is not None and (_under(target, _SNAPSHOT_STORE) or protected_deletion_root(target)))
        or ".btrbk" in parts or ".snapshots" in parts
        or any("snap" in part or "btrbk" in part for part in parts)
    )


def _btrfs_decision(tokens: Sequence[str], cwd: str) -> CommandGuardDecision | None:
    words = _positionals(tokens[1:], frozenset({"-i", "--subvolid", "--format"}))
    if len(words) < 3:
        return None
    group, action, targets = words[0], words[1], words[2:]
    if len(group) < 2 or not "subvolume".startswith(group) or not "delete".startswith(action):
        return None
    if any(_snapshot_target(target, cwd) for target in targets):
        return _system_blocked(
            "btrfs subvolume delete",
            "Deleting btrbk/snapper snapshots or subvolumes on protected storage destroys backup history; "
            "snapshot retention belongs to btrbk/snapper. Inspect with 'btrfs subvolume list'.",
            tokens,
        )
    return None


def _restic_decision(tokens: Sequence[str]) -> CommandGuardDecision | None:
    words = _positionals(tokens[1:], _RESTIC_OPTIONS_WITH_VALUE)
    if not words:
        return None
    dry_run = git_has_flag(tokens, "--dry-run") or "n" in _short_flags(tokens[1:])
    if (words[0] in {"forget", "prune"} and not dry_run) or (words[0] == "key" and words[1:2] in (["remove"], ["rm"])):
        return _system_blocked(
            f"restic {words[0]}",
            "Permanently deletes backup snapshots, data, or keys; retention runs only from the scheduled "
            "SummitFlow backup jobs. Inspect with 'restic snapshots' or preview with '--dry-run'.",
            tokens,
        )
    return None


def _rclone_decision(tokens: Sequence[str]) -> CommandGuardDecision | None:
    args = tokens[1:]
    command = next((arg for arg in args if arg in _RCLONE_DESTRUCTIVE), None)
    if command is None or git_has_flag(args, "--dry-run") or "-n" in args:
        return None
    if any(not arg.startswith("-") and arg != command and _RCLONE_REMOTE.match(arg) for arg in args):
        return _system_blocked(
            f"rclone {command}",
            "Deletes files on a remote (offsite backups such as summitflow-drive live there); offsite "
            "expiry runs only from the scheduled backup jobs. Inspect with 'rclone ls'/'rclone lsd' or add --dry-run.",
            tokens,
        )
    return None


def _find_decision(tokens: Sequence[str], cwd: str) -> CommandGuardDecision | None:
    args = list(tokens[1:])
    while args and (args[0] in _FIND_GLOBAL_OPTIONS or args[0].startswith("-O")):
        args = args[1:]
    if args[:1] == ["-D"]:
        args = args[2:]
    starts: list[str] = []
    while args and not args[0].startswith("-") and args[0] not in {"(", "!", ","}:
        starts.append(args.pop(0))
    deleting = "-delete" in args or any(
        arg in {"-exec", "-execdir", "-ok", "-okdir"} and index + 1 < len(args)
        and Path(args[index + 1]).name in _DELETING_EXECUTABLES
        for index, arg in enumerate(args)
    )
    if not deleting:
        return None
    selective = any(arg in _FIND_SELECTIVE for arg in args)
    for start in starts or ["."]:
        target = _deletion_target(start, cwd)
        if target is None:
            continue
        mounted = any(_under(target, root) for root in (*_MOUNTED_STORAGE_ROOTS, *_PROXMOX_DATA_ROOTS))
        if mounted or (protected_deletion_root(target) and not selective):
            return _system_blocked(
                f"find {target} -delete",
                "Bulk delete across a protected root (home, /srv, workspace or project root, mounted storage) "
                "is irreversible; narrow it with -name/-path to files you own, or delete specific subpaths.",
                tokens,
            )
    return None


def _proxmox_decision(name: str, tokens: Sequence[str]) -> CommandGuardDecision | None:
    words = _positionals(tokens[1:])
    advice = (
        "destroys Proxmox/LVM/ZFS storage or guests with no undo; VM and storage lifecycle is owner-run. "
        "Inspect with 'qm list', 'pct list', 'lvs', 'zfs list', or 'pvesm status'."
    )
    if name in {"qm", "pct"} and words[:1] == ["destroy"]:
        return _system_blocked(f"{name} destroy", f"This {advice}", tokens)
    if name in {"lvremove", "vgremove", "pvremove"} and not git_has_flag(tokens[1:], "-t", "--test"):
        return _system_blocked(name, f"This {advice}", tokens)
    if name in {"zfs", "zpool"} and words[:1] == ["destroy"] and "n" not in _short_flags(tokens[1:]):
        return _system_blocked(f"{name} destroy", f"This {advice}", tokens)
    if name == "pvesm" and words[:1] == ["free"]:
        return _system_blocked("pvesm free", f"This {advice}", tokens)
    return None


def irreversible_system_decision(tokens: Sequence[str], cwd: str) -> CommandGuardDecision | None:
    """Deny host-level irreversible commands: protected-root rm/find, disk and LUKS
    destruction, snapshot and backup deletion, and Proxmox guest/storage destroys."""
    if not tokens:
        return None
    name = Path(tokens[0]).name
    if name == "rm":
        return irreversible_rm_decision(tokens, cwd)
    if name == "find":
        return _find_decision(tokens, cwd)
    if name == "btrfs":
        return _btrfs_decision(tokens, cwd)
    if name == "restic":
        return _restic_decision(tokens)
    if name == "rclone":
        return _rclone_decision(tokens)
    return _disk_decision(name, tokens) or _proxmox_decision(name, tokens)


def ssh_remote_command(args: Sequence[str]) -> str | None:
    """Return the remote command string of an unwrapped ``ssh`` argv, if any."""
    index = 1
    while index < len(args) and args[index].startswith("-"):
        token = args[index]
        index += 1
        if token == "--":
            break
        for position, char in enumerate(token[1:], start=1):
            if char in _SSH_OPTIONS_WITH_VALUE:
                if position == len(token) - 1:
                    index += 1  # value is the next argument
                break
    remote = list(args[index + 1:])  # args[index] is the destination
    return " ".join(remote) if remote else None


def irreversible_segment_decision(tokens: Sequence[str], cwd: str) -> CommandGuardDecision | None:
    """Evaluate one unwrapped argv against the irreversible set (hook policy)."""
    decision = irreversible_system_decision(tokens, cwd)
    if decision:
        return decision
    parsed = git_invocation(tokens, cwd)
    if parsed is None:
        return None
    subcommand, args, git_cwd = parsed
    shared = not any(_under(git_cwd, root) for root in DISPOSABLE_ROOTS)
    return irreversible_git_decision(subcommand, args, normalize_segment(tokens), shared_checkout=shared)
